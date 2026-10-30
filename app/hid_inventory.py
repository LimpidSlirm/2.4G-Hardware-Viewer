from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass


_DIGCF_PRESENT = 0x00000002
_DIGCF_DEVICEINTERFACE = 0x00000010
_OPEN_EXISTING = 3
_ERROR_INSUFFICIENT_BUFFER = 122
_ERROR_NO_MORE_ITEMS = 259
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
_HIDP_STATUS_SUCCESS = 0x00110000
_HIDP_STATUS_USAGE_NOT_FOUND = 0xC0110004


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("InterfaceClassGuid", _GUID),
        ("Flags", wintypes.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class _SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("DevicePath", wintypes.WCHAR * 1),
    ]


class _HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.DWORD),
        ("VendorID", wintypes.WORD),
        ("ProductID", wintypes.WORD),
        ("VersionNumber", wintypes.WORD),
    ]


class _HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


@dataclass(frozen=True)
class HidInterface:
    path: str
    vendor_id: int
    product_id: int
    version: int
    usage_page: int | None
    usage: int | None
    input_report_length: int
    output_report_length: int
    feature_report_length: int

    @property
    def vid_pid(self) -> str:
        return f"{self.vendor_id:04X}:{self.product_id:04X}"


class HidInventoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeatureReport:
    interface: HidInterface
    report_id: int
    data: bytes


def _configure_functions() -> tuple[ctypes.WinDLL, ctypes.WinDLL, ctypes.WinDLL]:
    setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
    hid = ctypes.WinDLL("hid", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(_GUID)]
    hid.HidD_GetHidGuid.restype = None
    hid.HidD_GetAttributes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_HIDD_ATTRIBUTES),
    ]
    hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
    hid.HidD_GetFeature.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    hid.HidD_GetFeature.restype = wintypes.BOOLEAN
    hid.HidD_GetPreparsedData.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
    hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    hid.HidD_FreePreparsedData.restype = wintypes.BOOLEAN
    hid.HidP_GetCaps.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_HIDP_CAPS),
    ]
    hid.HidP_GetCaps.restype = ctypes.c_int32

    setupapi.SetupDiGetClassDevsW.argtypes = [
        ctypes.POINTER(_GUID),
        wintypes.LPCWSTR,
        wintypes.HWND,
        wintypes.DWORD,
    ]
    setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
    ]
    setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_SP_DEVICE_INTERFACE_DATA),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]
    setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL

    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.CancelIoEx.restype = wintypes.BOOL
    return setupapi, hid, kernel32


def _device_path(
    setupapi: ctypes.WinDLL,
    device_info_set: wintypes.HANDLE,
    interface_data: _SP_DEVICE_INTERFACE_DATA,
) -> str:
    required = wintypes.DWORD()
    setupapi.SetupDiGetDeviceInterfaceDetailW(
        device_info_set,
        ctypes.byref(interface_data),
        None,
        0,
        ctypes.byref(required),
        None,
    )
    if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER:
        raise HidInventoryError("Unable to query HID interface path size.")

    buffer = ctypes.create_string_buffer(required.value)
    detail = ctypes.cast(buffer, ctypes.POINTER(_SP_DEVICE_INTERFACE_DETAIL_DATA_W))
    detail.contents.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
    if not setupapi.SetupDiGetDeviceInterfaceDetailW(
        device_info_set,
        ctypes.byref(interface_data),
        buffer,
        required.value,
        ctypes.byref(required),
        None,
    ):
        raise HidInventoryError("Unable to read HID interface path.")
    path_offset = 4
    path_address = ctypes.addressof(buffer) + path_offset
    return ctypes.wstring_at(path_address)


def _inspect_interface(
    path: str,
    hid: ctypes.WinDLL,
    kernel32: ctypes.WinDLL,
) -> HidInterface | None:
    handle = kernel32.CreateFileW(
        path,
        0,
        3,
        None,
        _OPEN_EXISTING,
        0,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        return None
    try:
        attributes = _HIDD_ATTRIBUTES()
        attributes.Size = ctypes.sizeof(attributes)
        if not hid.HidD_GetAttributes(handle, ctypes.byref(attributes)):
            return None
        preparsed = ctypes.c_void_p()
        if not hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            return None
        try:
            caps = _HIDP_CAPS()
            status = hid.HidP_GetCaps(preparsed, ctypes.byref(caps))
            if status != _HIDP_STATUS_SUCCESS:
                return None
            return HidInterface(
                path=path,
                vendor_id=attributes.VendorID,
                product_id=attributes.ProductID,
                version=attributes.VersionNumber,
                usage_page=caps.UsagePage,
                usage=caps.Usage,
                input_report_length=caps.InputReportByteLength,
                output_report_length=caps.OutputReportByteLength,
                feature_report_length=caps.FeatureReportByteLength,
            )
        finally:
            hid.HidD_FreePreparsedData(preparsed)
    finally:
        kernel32.CloseHandle(handle)


def enumerate_hid_interfaces() -> list[HidInterface]:
    setupapi, hid, kernel32 = _configure_functions()
    hid_guid = _GUID()
    hid.HidD_GetHidGuid(ctypes.byref(hid_guid))
    device_info_set = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(hid_guid),
        None,
        None,
        _DIGCF_PRESENT | _DIGCF_DEVICEINTERFACE,
    )
    if device_info_set == _INVALID_HANDLE_VALUE:
        raise HidInventoryError("Unable to enumerate HID device interfaces.")

    interfaces: list[HidInterface] = []
    try:
        index = 0
        while True:
            interface_data = _SP_DEVICE_INTERFACE_DATA()
            interface_data.cbSize = ctypes.sizeof(interface_data)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                device_info_set,
                None,
                ctypes.byref(hid_guid),
                index,
                ctypes.byref(interface_data),
            ):
                if ctypes.get_last_error() == _ERROR_NO_MORE_ITEMS:
                    break
                index += 1
                continue
            index += 1
            try:
                path = _device_path(setupapi, device_info_set, interface_data)
                interface = _inspect_interface(path, hid, kernel32)
                if interface is not None:
                    interfaces.append(interface)
            except HidInventoryError:
                continue
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(device_info_set)
    return interfaces


def read_feature_report(interface: HidInterface, report_id: int = 0) -> bytes | None:
    if interface.feature_report_length <= 0:
        return None
    if not 0 <= report_id <= 0xFF:
        raise ValueError("Report ID must be between 0 and 255.")

    _, hid, kernel32 = _configure_functions()
    handle = kernel32.CreateFileW(
        interface.path,
        0,
        3,
        None,
        _OPEN_EXISTING,
        0,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        return None
    try:
        report = (ctypes.c_ubyte * interface.feature_report_length)()
        report[0] = report_id
        if not hid.HidD_GetFeature(
            handle,
            ctypes.cast(report, ctypes.c_void_p),
            interface.feature_report_length,
        ):
            return None
        return bytes(report)
    finally:
        kernel32.CloseHandle(handle)


def probe_feature_reports(
    interfaces: list[HidInterface],
    report_ids: range = range(0, 4),
) -> list[FeatureReport]:
    reports: list[FeatureReport] = []
    for interface in interfaces:
        if interface.feature_report_length <= 0:
            continue
        for report_id in report_ids:
            data = read_feature_report(interface, report_id)
            if data is not None:
                reports.append(FeatureReport(interface, report_id, data))
    return reports


def read_input_reports(
    interface: HidInterface,
    on_report,
    stop_event,
    buffer_size: int = 64,
) -> None:
    """Block on ReadFile and hand every input report to ``on_report``.

    pywinusb delivers reports through a Windows message loop, which does not run
    while a Qt event loop owns the thread, so this uses a plain blocking read on
    a dedicated thread instead. No report is ever written.
    """
    _, _, kernel32 = _configure_functions()
    handle = kernel32.CreateFileW(
        interface.path,
        0x80000000,  # GENERIC_READ
        3,  # FILE_SHARE_READ | FILE_SHARE_WRITE
        None,
        _OPEN_EXISTING,
        0,
        None,
    )
    if handle == _INVALID_HANDLE_VALUE:
        return
    try:
        buffer = (ctypes.c_ubyte * buffer_size)()
        read = wintypes.DWORD(0)
        while not stop_event.is_set():
            ok = kernel32.ReadFile(
                handle,
                ctypes.cast(buffer, ctypes.c_void_p),
                buffer_size,
                ctypes.byref(read),
                None,
            )
            if not ok:
                break
            if read.value:
                on_report(list(buffer[: read.value]))
    finally:
        kernel32.CancelIoEx(handle, None)
        kernel32.CloseHandle(handle)
