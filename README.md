# 2.4G Hardware Viewer

Windows 桌面浮层工具，实时查看已连接的 2.4G / USB / 蓝牙外设，并读取键盘、鼠标的真实电量。

只读取系统已公开的数据和设备厂商自有的只读报告，不抓取 2.4G 空中射频包，不发送任何 HID 写命令。

## 功能

- 透明、无边框、置顶浮层，可拖动到任意位置
- 设备按 `音频设备` / `键盘` / `鼠标` 三类分组展示
- 电量直接合并到对应设备行，同一台设备只出现一行，不额外新增条目
- 有电量的设备显示绿色电量条与百分比
- 无电量的设备明确标注 `电量未公开`，不猜测、不伪造百分比
- 每行显示状态圆点、设备名、VID:PID 与连接方式
- 点击设备行展开详情，再次点击收起；不点击时不占用空间
- 每 5 分钟自动刷新，也可随时手动刷新
- 过滤笔记本内置 ACPI/PS-2 键盘与内置麦克风阵列
- 窗口高度随内容自适应，上限 720 px，宽度固定 500 px

## 界面操作

| 操作 | 效果 |
| --- | --- |
| 拖动面板 | 移动窗口 |
| 点击设备行 | 展开 / 收起该设备详情 |
| `立即刷新` 或 `F5` | 立即重新读取设备 |
| `Ctrl + ↑` / `Ctrl + ↓` | 调整不透明度（35%–100%） |
| `Esc` | 关闭窗口 |

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
  hid_inventory.py      HID 接口枚举与诊断（工具）
requirements.txt
```

### `app/main.py` — 界面层

- `OverlayWindow`：透明浮层主窗口，负责分组渲染、详情面板、快捷键与定时刷新
- `DeviceDiscoveryThread`：`QThread` 后台线程，避免查询设备时界面卡顿
- `DeviceRow`：单台设备的行控件，包含状态圆点、电量条与百分比
- `_attach_battery()`：把协议读取到的电量挂到匹配的 PnP 设备行上；找不到对应设备时才单独列出
- 配色常量与 `_status_color()` / `_source_text()` 统一管理视觉语义：
  绿色 = 已确认读取或在线，黄色 = 候选未完全验证，红色 = 异常

### `app/device_discovery.py` — 设备发现

- 调用 PowerShell 查询 `AudioEndpoint`、`Keyboard`、`Mouse` 三类 PnP 设备
- `DeviceRecord` 数据模型：类别、名称、状态、实例 ID、电量
- 派生属性 `transport`（USB / HID / 蓝牙 / Windows 音频端点）与 `vid_pid`
- 过滤内置键盘与麦克风阵列，并对同一物理设备的多接口条目去重

### `app/battery_protocols.py` — 电量协议

- `read_vendor_battery_candidates()`：读取键盘接收器 `3554:FA09` 的 Feature Report 6
- `parse_rapoo_status()`：解析鼠标状态报告，并用 DPI 双轴做偏移自校验
- `read_mouse_battery()`：被动监听鼠标 Input Report 7，超时无报告则返回空

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
        │  _attach_battery()         → 按 VID:PID 合并到对应设备行
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
| 无线鼠标 | `24AE:1411` | Input Report 7（被动接收） | `[7]` 状态标志、`[8]` 电量百分比 |

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
- 外设电量取决于设备是否暴露只读报告；Windows 通用 PnP 属性中的 `PowerData` 属于电源管理元数据，不能当作电量
- 蓝牙耳机（如 HUAWEI FreeBuds SE 2）与普通 USB 音频设备目前读不到电量，Windows 设置中的合并电量未通过标准接口公开
- 鼠标休眠时不发送报告，此时显示为无读数，不会误报 `0%`；移动鼠标即可重新取值
- 键盘报告的三个候选字节尚未逐字节独立验证，界面标注为“候选”
- 不解析 2.4G 空中数据包，也不逆向未知设备协议
- 全程只读：不发送 Output Report 或 Feature Report 写命令，不读取键盘按键内容或鼠标移动轨迹
