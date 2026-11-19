"""Use the Windows Hello consent prompt from a desktop window."""
import ctypes
import sys
import time
import uuid
from ctypes import wintypes


_CLASS_NAME = "Windows.Security.Credentials.UI.UserConsentVerifier"
_IID_INTEROP = "39e050c3-4e74-441a-8dc0-b81104df949c"
_IID_ASYNC_INFO = "00000036-0000-0000-c000-000000000046"
_IID_ASYNC_RESULT = "fd596ffd-2318-558f-9dbe-d21df43764a5"
_RPC_E_CHANGED_MODE = 0x80010106
_RESULT_MESSAGES = {
    1: "Windows Hello has no verification device available.",
    2: "Windows Hello is not set up for this Windows account.",
    3: "Windows Hello is disabled by Windows policy.",
    4: "The Windows Hello device is busy. Try again.",
    5: "Windows Hello rejected too many attempts.",
    6: "Windows Hello verification was canceled.",
}


class _Guid(ctypes.Structure):
    _fields_ = [
        ("data1", ctypes.c_uint32),
        ("data2", ctypes.c_uint16),
        ("data3", ctypes.c_uint16),
        ("data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


def find_window(title):
    if sys.platform != "win32":
        return 0
    find_window = ctypes.WinDLL("user32", use_last_error=True).FindWindowW
    find_window.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    find_window.restype = wintypes.HWND
    return find_window(None, title)


def _check(hr, operation):
    if hr < 0:
        raise OSError(f"{operation} failed (HRESULT 0x{hr & 0xFFFFFFFF:08X})")


def _com_call(pointer, index, *args, argtypes=(), restype=ctypes.c_long):
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])
    hr = method(pointer, *args)
    _check(hr, "Windows Hello")
    return hr


def _release(pointer):
    if pointer and pointer.value:
        vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        release(pointer)


def _is_cancelled(cancelled):
    if cancelled is None:
        return False
    return cancelled() if callable(cancelled) else cancelled.is_set()


def _wait_for_result(operation, timeout, cancelled):
    info = ctypes.c_void_p()
    iid = _Guid.parse(_IID_ASYNC_INFO)
    _com_call(
        operation, 0, ctypes.byref(iid), ctypes.byref(info),
        argtypes=(ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)),
    )
    try:
        deadline = time.monotonic() + timeout
        status = ctypes.c_int32()
        while True:
            _com_call(info, 7, ctypes.byref(status), argtypes=(ctypes.POINTER(ctypes.c_int32),))
            if status.value == 1:
                result = ctypes.c_int32()
                _com_call(operation, 8, ctypes.byref(result), argtypes=(ctypes.POINTER(ctypes.c_int32),))
                return result.value
            if status.value == 2:
                return None
            if status.value == 3:
                error = ctypes.c_long()
                _com_call(info, 8, ctypes.byref(error), argtypes=(ctypes.POINTER(ctypes.c_long),))
                _check(error.value, "Windows Hello verification")
                raise OSError("Windows Hello verification failed.")
            if time.monotonic() >= deadline or _is_cancelled(cancelled):
                _com_call(info, 9)
                return None
            time.sleep(0.1)
    finally:
        _release(info)


def verify(hwnd, message, timeout=120, cancelled=None):
    """Return (verified, detail); never treats unavailable or failed verification as approval."""
    if sys.platform != "win32":
        return False, "Windows Hello is available only on Windows."
    if not hwnd:
        return False, "Jarvis's window could not be found for the Windows Hello prompt."

    combase = ctypes.WinDLL("combase")
    combase.RoInitialize.argtypes = [ctypes.c_uint32]
    combase.RoInitialize.restype = ctypes.c_long
    combase.RoUninitialize.argtypes = []
    combase.RoUninitialize.restype = None
    combase.WindowsCreateString.argtypes = [
        wintypes.LPCWSTR, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)
    ]
    combase.WindowsCreateString.restype = ctypes.c_long
    combase.WindowsDeleteString.argtypes = [ctypes.c_void_p]
    combase.WindowsDeleteString.restype = ctypes.c_long
    combase.RoGetActivationFactory.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)
    ]
    combase.RoGetActivationFactory.restype = ctypes.c_long

    initialized = combase.RoInitialize(1)
    owns_apartment = initialized >= 0
    if initialized < 0 and (initialized & 0xFFFFFFFF) != _RPC_E_CHANGED_MODE:
        _check(initialized, "Initializing Windows Hello")

    name = ctypes.c_void_p()
    text = ctypes.c_void_p()
    interop = ctypes.c_void_p()
    operation = ctypes.c_void_p()
    try:
        _check(
            combase.WindowsCreateString(_CLASS_NAME, len(_CLASS_NAME), ctypes.byref(name)),
            "Creating the Windows Hello class name",
        )
        _check(
            combase.WindowsCreateString(message, len(message), ctypes.byref(text)),
            "Creating the Windows Hello prompt",
        )
        iid = _Guid.parse(_IID_INTEROP)
        _check(
            combase.RoGetActivationFactory(name, ctypes.byref(iid), ctypes.byref(interop)),
            "Loading Windows Hello",
        )
        result_iid = _Guid.parse(_IID_ASYNC_RESULT)
        _com_call(
            interop, 6, wintypes.HWND(hwnd), text, ctypes.byref(result_iid), ctypes.byref(operation),
            argtypes=(
                wintypes.HWND, ctypes.c_void_p, ctypes.POINTER(_Guid),
                ctypes.POINTER(ctypes.c_void_p),
            ),
        )
        result = _wait_for_result(operation, timeout, cancelled)
        if result == 0:
            return True, "Windows Hello verified."
        if result is None:
            return False, "Windows Hello verification was canceled or timed out."
        return False, _RESULT_MESSAGES.get(result, f"Windows Hello returned unexpected result {result}.")
    except OSError as exc:
        return False, str(exc)
    finally:
        _release(operation)
        _release(interop)
        if text.value:
            combase.WindowsDeleteString(text)
        if name.value:
            combase.WindowsDeleteString(name)
        if owns_apartment:
            combase.RoUninitialize()
