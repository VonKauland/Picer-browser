# Picer 插件系统 v1

揽映将图片处理能力放在插件层。内置 `picer.transforms` 使用与第三方相同的 SDK 提供旋转、水平翻转和灰度预览；主窗口负责图片显示、文件导航和窗口操作。插件不需要修改宿主源码。

## 架构与生命周期

```mermaid
flowchart LR
    Package[插件 ZIP / 插件目录] --> Manifest[清单校验与 API 兼容检查]
    Manifest --> Manager[PluginManager]
    Manager --> Context[PluginContext SDK]
    Context --> Commands[菜单命令]
    Context --> Events[图片事件]
    Context --> Settings[插件独立配置]
    Context --> Tasks[后台任务]
    Tasks --> Result[GUI 线程回调]
    Result --> Image[当前图片预览]
```

- 发现只读取 `manifest.json`，不会导入代码。新安装的第三方插件默认停用。
- 启用时先按依赖关系加载依赖，再导入入口类并调用 `activate(context)`。依赖缺失、循环、API 不兼容会阻止启用。
- 激活失败时撤销部分注册；此次新启用的依赖也回滚，原已启用依赖保持运行。
- 停用时先撤销上下文，再调用可选的 `deactivate()`。无论清理钩子是否抛出普通异常，宿主都会删除菜单命令、快捷键、事件订阅和模块命名空间，并取消后台任务。
- 停用有运行中依赖者的插件会被拒绝，需先停用依赖者。关闭应用按依赖者优先的顺序清理。
- 插件命令、事件、激活和后台任务抛出的普通 Python 异常会被记录；出错插件和依赖它的插件会停用，宿主保留当前图片。
- 重载先停用再重新校验清单、清理字节码缓存并重新导入；重载失败保持停用，不继续使用旧实例。
- 更新只允许覆盖已停用的第三方插件，保留独立配置并保持停用。不能覆盖或卸载内置插件。

## 用户操作

打开 **插件 → 插件管理**，或按 `Ctrl+Shift+P`：

1. 选择 **安装/更新 ZIP…**，安装后查看名称、版本、来源、权限、依赖和错误。
2. 确认来源可信后点击 **启用**，依赖会一并启用。
3. 插件命令出现在 **插件** 菜单；插件也可贡献到 **编辑**、**视图** 菜单。
4. 可停用、重载或卸载；更新前先停用，卸载同时删除该插件配置。

**打开插件目录** 可查看实际存储位置。文件夹版本默认使用 EXE 所在目录保存数据；源码开发或软件目录不可写时使用用户目录。也可通过 `--data-dir` 指定位置。

```text
Picer/
  Picer.exe
  config/plugins.json           启用状态与插件独立设置
  logs/plugins.log              异常日志（256 KiB 轮转，保留两份旧日志）
  cache/
    thumbnails/                 宿主缩略图缓存
    plugins/<plugin-id>/        插件独立缓存
  plugins/
    example.negative/
      manifest.json
      main.py
```

资源、迁移与备份规则详见 [文件夹分发指南](distribution.md)。

配置使用临时文件与原子替换保存。无法读写配置时仍允许查看图片，诊断显示在插件管理中。直接复制目录的插件在下次启动发现；改动运行中插件的源码后点击 **重载**。

出现第三方插件启动问题时可运行 `Picer.exe --safe-mode`，本次跳过第三方发现和自动启用，不删除插件或改写其启用偏好。内置插件仍按已有偏好加载。

## 插件包结构

ZIP 根目录直接包含清单与入口，不能额外包一层文件夹：

```text
negative-plugin.zip
  manifest.json
  main.py
  helper.py                     可选：通过相对导入使用
  resources/                    可选资源
```

安装器限制为最多 500 项、解压后最多 20 MiB，并拒绝路径穿越、符号链接、重复路径、大小写冲突和 Windows 特殊路径。安装校验是文件完整性检查，不证明代码可信。

`manifest.json`：

```json
{
  "id": "example.negative",
  "name": "负片预览",
  "version": "1.0.0",
  "api_version": 1,
  "entrypoint": "main:Plugin",
  "description": "当前图片反色预览，不修改原文件。",
  "author": "Your Name",
  "permissions": ["ui.commands", "image.read", "image.modify", "tasks"],
  "requires": []
}
```

| 字段 | 规则 |
| --- | --- |
| id | 稳定、全局唯一，小写字母开头的点分标识符；内置 id 为 `picer.transforms` |
| name / version | 非空名称；版本格式 `major.minor.patch` |
| api_version | 当前仅支持整数 `1`，不匹配的插件不执行 |
| entrypoint | `module:Class`；模块可为多层包，如 `effects.main:Plugin` |
| permissions | API 能力声明，见下表 |
| requires | 插件 id 列表；v1 校验依赖存在及依赖自身的 API 兼容，不解析插件版本范围 |
| description / author | 可选字符串 |

`main.py` 最小示例：

```python
from picer.plugins import PluginContext

class Plugin:
    def activate(self, context: PluginContext):
        self.context = context
        context.add_command("invert", "反色预览", self.invert)

    def invert(self):
        image = self.context.image()
        image.invertPixels()
        self.context.replace_image(image)

    def deactivate(self):
        pass
```

注册 ID 在每个插件内唯一；宿主内部使用 `插件id:命令id`。快捷键与宿主及其他运行中插件冲突时会拒绝注册并回滚激活。默认 `requires_image=True`，未打开图片时命令不可用。

多文件插件使用 `from .helper import ...`；宿主给每个插件分配独立模块命名空间，不向全局 `sys.path` 插入插件目录。插件资源可基于模块的 `__file__` 定位。

## SDK API

| 权限 | API | 行为 |
| --- | --- | --- |
| ui.commands | `add_command(id, label, callback, shortcut="", requires_image=True, menu="插件")` | 在支持的菜单注册动作，停用时自动删除 |
| image.read | `current_path()` | 返回当前 `Path`，未打开图片时为 `None` |
| image.read | `image()` | 返回当前预览的独立 `QImage` 拷贝，包含当前显示变换 |
| image.read | `thumbnail()` | 返回当前原图的独立缩略图拷贝，不含插件预览变换 |
| cache | `cache_directory()` | 返回 `cache/plugins/<plugin-id>` 独立目录，插件自行控制容量 |
| image.modify | `replace_image(image)` | 更新显示并适应窗口，发出图片变更事件；不写原文件 |
| events.subscribe | `subscribe(name, callback)` | 订阅图片事件，停用时自动撤销 |
| settings | `get_setting(key, default=None)` / `set_setting(key, value)` | 插件命名空间下的 JSON 设置；读取返回副本，单值最多 64 KiB 序列化 JSON |
| tasks | `run_task(work, on_result, image_bound=True)` | 后台计算，结果在 GUI 线程交付，返回取消令牌 |
| 无额外声明 | `notify(message)` | 显示信息对话框 |

所有上下文 API 必须在 GUI 线程调用；停用后的上下文不可继续使用。插件清理钩子自行停止自己创建的资源，不应再注册命令或访问上下文。

### 事件

- `image.opened`：成功打开图片后发送。
- `image.changed`：打开或替换当前预览后发送。

回调参数为不可变 `ImageEvent(path, width, height, reason)`；`reason` 为 `opened` 或 `edited`。事件是发送开始时的元数据快照。事件回调中再次替换图片会更新画面，但不递归发送新的事件，避免反馈循环。

### 后台任务

大图计算应使用工作线程。先在 GUI 线程获取图片拷贝，工作函数接收 `TaskToken`：

```python
image = context.image()

def work(token):
    token.checkpoint()
    image.invertPixels()
    token.checkpoint()
    return image

token = context.run_task(work, context.replace_image)
# token.cancel() 请求取消；token.cancelled 查询状态。
```

工作线程禁止调用上下文或操作 QWidget/QPixmap；使用独立的 QImage 数据计算。`on_result` 在 GUI 线程调用，可以使用上下文。插件停用后结果丢弃；默认情况下，用户切换图片或修改预览后，旧任务结果也丢弃。与图片无关的工作可指定 `image_bound=False`。最多同时排队 16 个插件任务。

取消是协作式的；工作函数应定期 `checkpoint()`。宿主不会强制杀死 Python 线程，无法中断不配合的无限循环或阻塞原生调用。

## 随附示例与构建验证

`examples/negative_plugin` 展示菜单、图片读写、事件、设置和后台任务。Windows Actions 会将其打包为 `Picer/examples/negative-plugin.zip`，随完整软件文件夹上传。

手动打包：

```powershell
Compress-Archive -Path examples/negative_plugin/* -DestinationPath negative-plugin.zip -Force
```

CI 在实际 EXE 中安装这个外部 ZIP、启用插件、读取 PNG/JPEG、执行内置旋转及外部异步反色、检查配置和停用清理，以验证冻结后动态导入仍可用。

## 运行边界与演进

v1 是可信 Python 插件系统，运行在宿主进程中。权限声明只控制 SDK 调用，不能阻止插件直接访问文件、网络或 Python 私有对象。普通异常隔离不覆盖原生崩溃、主动退出或恶意代码；需要运行不可信扩展时，后续应增加独立进程与受限 IPC，而不是把当前声明误称为沙箱。

冻结 EXE 中只保证宿主已打包的 Python/Qt 模块可用。不会自动执行 pip 或下载依赖。插件可携带纯 Python 相对导入模块；额外原生库、未打包标准库模块或其他 Qt 模块需要专门适配和构建验证。

后续可在稳定 SDK 上增加：独立进程插件、解码器与导出器注册、参数面板、撤销栈、插件版本依赖范围与签名分发。目前没有实现插件商店、网络更新或不可信插件沙箱。
