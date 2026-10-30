# 2.4G Hardware Viewer

Windows 桌面浮层工具，实时查看已连接的 2.4G / USB / 蓝牙外设，并读取键盘、鼠标的真实电量。

只读取系统已公开的数据和设备厂商自有的只读报告，不抓取 2.4G 空中射频包，不发送任何 HID 写命令。

## 功能

- 透明、无边框、置顶浮层，可拖动到任意位置
- 默认以迷你电量窗启动（约 210 px 宽），只显示键盘与鼠标电量条
- `Ctrl + Alt + B` 全局快捷键或双击迷你窗，切换到完整界面，再按一次回到迷你窗
- 完整界面按 `音频设备` / `键盘` / `鼠标` 三类分组展示
- 按物理设备合并：同一个 2.4G 接收器的键盘、鼠标、多媒体等 HID 集合只显示一行，可同时展示键盘与鼠标电量
- 有电量的设备显示绿色电量条与百分比
- 无电量的设备明确标注 `电量未公开`，不猜测、不伪造百分比
- 每行显示状态圆点、设备名、VID:PID 与数据来源
- 点击设备行展开详情，再次点击收起；不点击时不占用空间
- 鼠标休眠时不广播报告，界面沿用最后一次有效读数并标注 `缓存 HH:MM`
- 每 5 分钟自动刷新，也可随时手动刷新
- 过滤笔记本内置 ACPI/PS-2 键盘、内置麦克风阵列与内置触摸板
- 窗口高度随内容自适应，最大不超过屏幕可用高度
- 支持写入开机自启项（当前用户 `Run` 项，使用 `pythonw.exe` 无黑窗启动）

## 界面操作

| 操作 | 效果 |
| --- | --- |
| `Ctrl + Alt + B` | 迷你窗 ⇄ 完整界面（全局生效） |
| 双击窗口 | 迷你窗 ⇄ 完整界面 |
| 拖动面板 | 移动窗口 |
| 点击设备行 | 展开 / 收起该设备详情 |
| `F5` | 立即重新读取设备 |
| `Ctrl + ↑` / `Ctrl + ↓` | 调整不透明度（35%–100%） |
| `Esc` | 关闭窗口 |

## 开机自启

```powershell
python -m app.main --install-autostart   # 写入自启项
python -m app.main --remove-autostart    # 移除自启项
```

写入位置：

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
  2.4G-Hardware-Viewer = "<pythonw.exe>" "<项目>\launch.pyw"
```

使用 `pythonw.exe`，开机时不会弹出控制台窗口。

## 技术框架

| 层 | 技术 |
| --- | --- |
| 语言 | Python 3.13 |
| 界面 | PySide6（Qt 6） |
| 设备枚举 | Windows PowerShell `Get-PnpDevice` |
| 厂商电量协议 | `pywinusb`（HID 只读） |
| HID 诊断 | `ctypes` 直调 `hid.dll` / `setupapi.dll` |
| 预留扩展 | `pyserial`（串口型设备） |

## 模块结构

```text
app/
  __init__.py
  main.py               界面与交互层
  device_discovery.py   Windows 设备发现
  battery_protocols.py  厂商电量协议解析
  hotkey.py             Win32 全局快捷键
  autostart.py          开机自启项读写
  hid_inventory.py      HID 接口枚举与诊断（工具）
launch.pyw              自启动用的无控制台入口
requirements.txt
```

### `app/main.py` — 界面层

- `OverlayWindow`：透明浮层主窗口，负责分组渲染、详情面板、快捷键与定时刷新
- `DeviceDiscoveryThread`：`QThread` 后台线程，避免查询设备时界面卡顿
- `DeviceRow`：单台设备的行控件，包含状态圆点、电量条与百分比
- `_merge_by_device()`：按 VID:PID 把同一物理设备的多个 HID 集合合并成一行，
  并在该行同时显示键盘与鼠标的电量
- 配色常量与 `_status_color()` / `_meta_text()` 统一管理视觉语义：
  绿色 = 已确认读取或在线，黄色 = 候选未完全验证，红色 = 异常

### `app/device_discovery.py` — 设备发现

- 调用 PowerShell 查询 `AudioEndpoint`、`Keyboard`、`Mouse` 三类 PnP 设备
- `DeviceRecord` 数据模型：类别、名称、状态、实例 ID、电量
- 派生属性 `transport`（USB / HID / 蓝牙 / Windows 音频端点）与 `vid_pid`
- 过滤内置键盘与麦克风阵列，并对同一物理设备的多接口条目去重

### `app/battery_protocols.py` — 电量协议

- `read_vendor_battery_candidates()`：读取键盘接收器 `3554:FA09` 的 Feature Report 6
- `parse_keyboard_battery()`：取 `0C45:FEFE` 类型 `0x10` 厂商报文的 `[26]` 作为电量原始值
- `read_keyboard_battery()`：返回最近 5 次读数的中位数，带落盘缓存以应对空闲期
- `parse_rapoo_status()`：解析鼠标状态报告，并用 DPI 双轴做偏移自校验
- `read_mouse_battery()`：被动监听鼠标 Input Report 7，静默时返回带 `cached` 标记的最后读数
- `_listen_mouse_report()`：单次监听，不发送任何报告

### `app/hotkey.py` — 全局快捷键

- 通过 `RegisterHotKey` 注册系统级 hotkey，`QAbstractNativeEventFilter` 接收 `WM_HOTKEY`
- 默认绑定 `Ctrl + Alt + B`，用于切换迷你/完整界面

### `app/autostart.py` — 开机自启

- 读写当前用户 `Run` 项，命令指向 `pythonw.exe` + `launch.pyw`
- 提供安装、移除、读取三种操作

### `app/hid_inventory.py` — HID 诊断工具

只读枚举系统中的 HID 接口，输出 VID/PID、Usage Page、Usage 以及各类报告长度，
并可在安全范围内读取 Feature Report。该模块不参与日常界面流程，用于排查新设备的协议入口。

## 数据流

```text
定时器(5 分钟) / 刷新按钮 / F5
        │
        ▼
DeviceDiscoveryThread (QThread)
        │  discover_devices()        → PowerShell → PnP 设备列表
        │  read_vendor_battery_candidates() → 3554:FA09 Feature Report 6
        │  read_mouse_battery()      → 24AE:1411 Input Report 7
        │  _merge_by_device()        → 按 VID:PID 合并各 HID 集合
        ▼
list[DeviceRecord] ──Qt 信号──► OverlayWindow
        │
        ▼
分组渲染 DeviceRow → 电量条 / 详情面板
```

## 已支持的设备协议

| 设备 | VID:PID | 读取方式 | 字段 |
| --- | --- | --- | --- |
| 无线键盘接收器 | `3554:FA09` | Feature Report 6（只读） | 字节 `[3..5]` 为候选电量，当前三个值均一致 |
| 无线键盘 | `0C45:FEFE` | 监听 `0xFF60` 广播（被动） | 类型 `0x10` 报文的 `[26]`，中位数平滑，实验性 |
| 无线鼠标 | `24AE:1411` | Input Report 7（被动接收） | `[7]` 状态标志、`[8]` 电量百分比 |

`0C45:FEFE` 只被动推送 33 字节厂商报文，不响应任何查询。字段判定过程：`[1]` 恒为 `0x55`，最初被当作 BCD 电量 55，后经总电量从 55 涨到 56 时该字节仍为 `0x55` 而证伪，确认是固定帧头。最终锁定类型 `0x10` 报文的 `[26]`：它随充电单调上升（51→54→58），均值与键盘显示值偏差不到 1，但抖动约 ±4，因此取最近 5 次的中位数并标注为实验性。

鼠标报告的偏移通过 DPI 自校验确认：

```text
[7, 16, 3, 64, 6, 64, 6, 1, 100, 0, 2, 2, 0]
 |   |  |  └─┬─┘ └─┬─┘  |   └─ 电量 100%
 |   |  |   X=1600  Y=1600  状态
 |   |  DPI 档位
 |   设备标识
 Report ID 7
```

`[3..4]` 与 `[5..6]` 解出 `1600 x 1600`，两轴同时落在合理范围才认为偏移正确，否则丢弃该报告。

## 运行

需在项目目录内执行：

```powershell
python -m app.main
```

启动自检（不显示窗口，仅验证初始化）：

```powershell
python -m app.main --smoke-test
```

## 环境依赖

```powershell
python -m pip install -r requirements.txt
```

```text
PySide6==6.9.2
pyserial==3.5
pywin32
pywinusb
```

## 已知限制

- 仅支持 Windows
- 一台 2.4G 接收器会注册多个 HID 集合，程序按 VID:PID 合并为一行；但如果两台不同设备恰好共用同一个 VID:PID，也会被合并
- 内置触摸板（`HID\UNIW...`）与内置键盘、麦克风阵列一样被过滤，不参与显示
- 外设电量取决于设备是否暴露只读报告；Windows 通用 PnP 属性中的 `PowerData` 属于电源管理元数据，不能当作电量
- 蓝牙耳机（如 HUAWEI FreeBuds SE 2）与普通 USB 音频设备目前读不到电量，Windows 设置中的合并电量未通过标准接口公开
- 鼠标休眠时不发送报告，此时沿用最后一次有效读数并标注 `缓存 HH:MM`；超过 24 小时未更新则回退为无读数，不会误报 `0%`
- 电量缓存只保存在进程内存中，程序重启后需要一次新的广播才能恢复读数（移动鼠标即可触发）
- 键盘报告的三个候选字节尚未逐字节独立验证，界面标注为“候选”
- 不解析 2.4G 空中数据包，也不逆向未知设备协议
- 全程只读：不发送 Output Report 或 Feature Report 写命令，不读取键盘按键内容或鼠标移动轨迹
