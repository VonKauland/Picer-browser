# 揽映组件规则（Picer 0.7）

组件只有三种类型。新开发必须显式声明 `type`，不可混用按钮、面板和皮肤入口。API 仍为 v1，已有图片、事件、配置和任务接口继续可用。

| 类型 | 清单 type | 注册规则 | 安装目录 | 用户操作 |
| --- | --- | --- | --- | --- |
| 皮肤 | `skin` | 声明式 JSON/QSS，无 Python 入口、权限和依赖 | `skins/<id>/` | 插件 → 皮肤，单选，或恢复默认暗黑 |
| 功能 | `function` | 必须且只能 `add_command()` 一次 | `plugins/<id>/` | 插件 → 功能勾选启停；调用功能执行；可绑定快捷位 |
| 面板 | `panel` | 必须且只能 `add_panel()` 一次，不能注册功能按钮 | `plugins/<id>/` | 插件 → 面板启停；固定/自动隐藏只通过三点条/隐藏条操作 |

安装器自动按类型分流，安装皮肤存储到 `skins` 文件夹。用户安装的第三方组件保持停用，用户主动启用后才应用。皮肤资源在安装和启用时校验；损坏皮肤不替换当前皮肤。更新和重载不允许改变类型，改类型需先卸载再安装。

## 五个功能快捷位

五个 28×28 小按钮位于合并后的顶栏右侧，窗口控制按钮左边。保持无底栏、文件名居中。默认绑定旋转、翻转、灰度，剩余两个留空。

- 通过 **插件 → 功能** 直接勾选或取消功能组件，随后通过 **调用功能** 菜单或已绑定的快捷位执行。
- 右键栏位选择已启用功能或清空；也可从 **插件 → 快捷栏位** 配置。
- 绑定保存到 `config/plugins.json` 的 `ui.quick_slots`，随整个软件目录迁移。
- 未打开图片时依赖图片的按钮不可执行；右键不便使用时可通过快捷栏位菜单配置。
- 停用或出错时立即解绑正在使用的 QAction，保留栏位的命令标识；重新启用后恢复。卸载时清除该组件绑定。

按钮图标由宿主绘制，名称、快捷键和说明在菜单/提示中显示，避免插件按钮破坏整体 UI。

## 功能组件

`manifest.json`：

```json
{
  "id": "example.negative",
  "name": "负片预览",
  "version": "1.1.0",
  "api_version": 1,
  "type": "function",
  "entrypoint": "main:Plugin",
  "permissions": ["ui.commands", "image.read", "image.modify", "tasks"]
}
```

```python
class Plugin:
    def activate(self, context):
        self.context = context
        context.add_command("negative", "负片预览", self.run)

    def run(self):
        image = self.context.image()
        image.invertPixels()
        self.context.replace_image(image)
```

多功能包应拆为多个不同 id 的功能组件，共享代码可使用各自包内模块。宿主内置旋转、翻转和灰度也已拆成三个组件。现有 `picer.transforms:rotate` 标识保留。

## 皮肤组件

ZIP 根目录包含：

```text
manifest.json
 theme.json
 skin.qss       可选
```

清单无 `entrypoint`，无权限和依赖：

```json
{
  "id": "example.skin",
  "name": "自定义皮肤",
  "version": "1.0.0",
  "api_version": 1,
  "type": "skin",
  "theme": "theme.json"
}
```

`theme.json`：

```json
{
  "colors": {
    "background": "#131820",
    "title": "#1c2531",
    "text": "#dde8f5",
    "menu": "#202c3c",
    "border": "#34445b",
    "hover": "#2f4058",
    "muted": "#91a5be"
  },
  "stylesheet": "skin.qss"
}
```

颜色值只接受 `#RRGGBB`，未指定项使用默认值。`stylesheet` 可省略；如填写，必须是同包根目录的 `.qss` 文件，最多 256 KiB。基础颜色覆盖宿主的窗口、顶栏、菜单、面板和画布；QSS 可进一步更改宿主控件样式，自动限定到宿主标记，保留插件自己的样式与图标。图片画布背景由 `background` 控制，避免 QGraphicsView 画刷覆盖皮肤。不要在 QSS 内使用依赖工作目录的相对资源 URL。

同一时刻只启用一款皮肤，选择另一款会停用原皮肤；恢复默认或卸载前停用即可。皮肤没有 Python 激活代码，也不会导入包内 `.py` 文件。

## 面板组件

```json
{
  "id": "example.info",
  "name": "图片信息",
  "version": "1.0.0",
  "api_version": 1,
  "type": "panel",
  "entrypoint": "main:Plugin",
  "permissions": ["ui.panels", "image.read", "events.subscribe"]
}
```

```python
from PySide6.QtWidgets import QLabel, QWidget, QVBoxLayout

class Plugin:
    def activate(self, context):
        panel = QWidget()  # 必须是新的、无父级的 QWidget
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("面板内容"))
        context.add_panel(panel, area="right")
```

普通面板默认 `panel_role: side`，`area` 只允许 `left`、`right`。只有显式声明 `"panel_role": "progress"` 的进度面板可使用 `area="bottom"`；它只允许底部且全窗口同时只能有一个进度面板。进度面板是居中悬浮条，不挤占左右面板的底部空间。保存的非法旧位置会回到该组件允许的默认边。宿主拥有无标题、无外边框毛玻璃外壳与内侧三点条；组件只提供内容 QWidget。

- 普通模式启用的面板默认固定。三点条右键或双击切换自动隐藏；隐藏不等于停用。菜单与应用设置中没有「显示：名称」开关。
- 悬停隐藏细条展开，点击细条固定；侧面板 Shift 拖动三点条或拖动细条可左右换边。进度面板只留在底部。
- 普通模式固定/自动隐藏偏好、停靠边和侧面板宽度保存并在重启恢复。
- 全屏默认自动隐藏全部面板；通过指示条临时固定，退出全屏恢复普通模式偏好。
- 停用、激活失败或出错时清理面板、上下文、事件和任务。


面板创建和界面操作仅限 GUI 线程。耗时工作通过 `context.run_task()` 执行，在结果回调中更新面板；不在工作线程操作 QWidget。

## 旧插件迁移

没有 `type` 的旧 API v1 插件暂归为功能类兼容组件，并在管理界面标注“旧版兼容”。兼容组件保留旧版多命令行为；添加 `type: function` 后立即按单按钮规则校验。新示例均声明类型。皮肤和面板必须显式声明类型，不能通过兼容入口跨类型注册。

兼容入口用于迁移旧配置；新项目必须显式声明类型并拆分多功能。SDK 权限只控制宿主 API，不是 Python 安全沙箱。

## 示例与验证

分发包 `examples/` 提供四个主要示例 ZIP：`file-browser.zip`、`info-panel.zip`、`progress-panel.zip`（面板），以及 `macos-skin.zip`（皮肤）。旧功能回归示例为 `sdk/negative-plugin.zip`。源码分别在对应的 examples 子目录。

自动化测试覆盖类型校验、贡献数量限制、激活失败清理、皮肤单选与回退、菜单启停、快捷位持久化和面板全屏规则。Windows 打包验证实际 EXE 的三类组件、快捷位调用、全屏面板隐藏及整目录移动后的配置保留。人工桌面视觉测试需要另行执行。

统一设置、四个示例、毛玻璃和隐藏条动效详见 [示例组件说明](example-components.md)。`add_panel` 返回宿主 QDockWidget，可监听 dockLocationChanged 调整内部布局。皮肤 QSS 自动限定到宿主控件，插件内容不会继承皮肤。

皮肤 theme.json 仍接受 `chrome: "macos"` 使用紧凑菜单间距，以兼容已有皮肤。所有皮肤的窗口按钮统一在右侧使用 32×32 的黄/绿/红细线按钮，按用户参考图保持大小和排列一致。它不修改操作系统或磁盘 EXE 图标。

随应用分发的五个示例已默认安装，面板与功能默认启用，皮肤默认关闭；这些默认值只在首次提供该示例时应用，后续尊重用户停用、卸载及设置。
