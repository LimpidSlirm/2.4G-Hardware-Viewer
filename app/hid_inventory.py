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
