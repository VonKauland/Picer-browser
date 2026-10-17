# 对焦点与人脸记录

图片信息面板的「显示对焦点」开关同时控制两类叠加：实线表示记录的对焦位置／区域，虚线表示记录的人脸区域。仅有中心坐标、没有宽高的人脸记录显示为小型虚线定位标记，不将标记尺寸解释为真实人脸范围。点坐标没有区域尺寸时，对焦框同样只是位置标记。

所有标记跟随 EXIF 方向、手动旋转、缩放和平移；切图、修改图像几何或停用组件后清除。程序不做图像人脸检测，也不根据画面内容推测焦点。

## 原生记录覆盖

厂商名称不等于该厂商全部机型、固件或拍摄模式都受支持；下表列出当前实际解析的结构。

| 厂商／系列 | 对焦记录 | 人脸记录 |
| --- | --- | --- |
| 佳能 | JPEG／CR2／CR3 的 AFInfo、AFInfo2 合焦位图 | FaceDetect1 中心坐标，显示定位标记；有标准 XMP 时显示完整框 |
| 尼康 | AFInfo2 0100／0101 的反差对焦坐标，0300／0301、0400／0401／0402 中有效的 AF 坐标；仅记录点编号的模式不猜测位置 | FaceDetect 的矩形与参考画幅 |
| 索尼 | Tag202a 多点坐标、有效 FocusFrameSize 对应的 FocusLocation；Flexible Spot 仅在匹配的 AF 模式下使用 | ShotInfo 中已确认的 0x48／0x20、0x5e／0x25 记录布局 |
| 富士 | FocusPixel；RAF 从内嵌 JPEG 的 EXIF 读取 | FacePositions 的完整图像矩形 |
| 松下／部分徕卡 | Panasonic MakerNotes 的 AFPointPosition；RW2／RWL 从 JpgFromRaw 读取 EXIF | FaceDetInfo 的矩形；不将 FaceRecInfo 中的姓名等身份信息绘制或导出 |
| 奥林巴斯／OM System | CameraSettings.AFPointSelected 的有理数坐标 | ImageProcessing 的四角坐标形式；尚未支持另一个旋转正方形编码 |
| 宾得／理光 GR III、GR IIIx、GR IV | AFInfoK3III 的已合焦区域、ContrastDetectAFArea | FaceInfoK3III 完整矩形；旧 FaceInfo 中心点为定位标记 |
| 旧款理光 GR | Ricoh MakerNotes 的 AFStatus 与完整画幅 AF 坐标；是否可用取决于原始文件实际记录 | Ricoh FaceInfo 的矩形与参考画幅 |
| 适马 fp／fp L | **原生焦点结构尚待原始样片确认，不能声称已支持** | 可读取文件内的标准 XMP 人脸框；尚不能声称已支持原生专有字段 |

三星、哈苏、徕卡等采用相同兼容 MakerNotes 结构的机型可走对应解析器；无法确认结构的机型不会按厂商名称硬套坐标。

## 所有厂商的通用人脸区域

JPEG、PNG、WebP、TIFF 及 TIFF 系 RAW 中如保留标准 MWG Regions 或 Microsoft Photo Region Rectangle，按这些记录显示人脸框，与相机厂商无关。支持有明确 `normalized` 单位的 MWG 人脸矩形，不把动物或其他类型区域当作人脸。不自动扫描或加载同名外部 XMP 文件。

这表示所有厂商都有通用读取路径，**不表示每个厂商的专有 MakerNotes 都已完全破解**。适马 fp／fp L 需要原始 DNG／直出 JPEG 对照样片（已知对焦位置，以及开启人脸识别拍摄的照片），才能验证未公开字段及固件差异。缺少坐标、无效值、未知版本、只有点编号或者被编辑软件移除记录时，保持空结果。

## 读取边界与兼容性

- 原生解析在元数据后台任务中执行，不依赖 RAW 像素解码成功。
- TIFF 按 IFD 指针定点读取，最多读取 2 MiB；RAF／RW2 只遍历内嵌 JPEG 的头部，不扫描像素流。拒绝越界偏移、异常数量、非有限数及无效参考画幅。
- 最多 512 个对焦区域、64 个人脸框和 64 个人脸中心。标准 XMP 限长并拒绝 DTD／实体声明。
- 未增加 ExifTool、Perl 或其他运行时依赖；ExifTool 仅在开发时用于对照字段定义和其公开测试数据。
- 新增专项测试使用结构化元数据夹具，不能替代每个实际机型／固件的真实照片验证。

字段依据：[ExifTool 标签文档](https://exiftool.org/TagNames/index.html)，及其 [MakerNotes](https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/MakerNotes.pm)、[Nikon](https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/Nikon.pm)、[Sony](https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/Sony.pm)、[FujiFilm](https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/FujiFilm.pm)、[Panasonic](https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/Panasonic.pm)、[Olympus](https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/Olympus.pm)、[Pentax](https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/Pentax.pm)、[Ricoh](https://github.com/exiftool/exiftool/blob/master/lib/Image/ExifTool/Ricoh.pm) 数据结构说明。
