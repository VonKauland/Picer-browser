; Current-user installer. All optional registration is HKCU and reversible.
; Python generates registry.iss from the actual build's image-format catalog.
[Setup]
AppId={#AppIdentifier}
AppName=揽映 Picer
AppVersion={#AppVersion}
AppPublisher=VonKauland
AppPublisherURL=https://github.com/VonKauland/Picer-browser
AppSupportURL=https://github.com/VonKauland/Picer-browser/issues
DefaultDirName={localappdata}\Programs\Picer
DefaultGroupName=揽映 Picer
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile={#SourceDir}\assets\icons\picer.ico
UninstallDisplayIcon={app}\Picer.exe
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
UsePreviousTasks=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupWindowTitle=揽映 Picer 安装
WelcomeLabel1=欢迎安装揽映 Picer
WelcomeLabel2=安装程序将在您的电脑上安装 [name/ver]。%n%n请先关闭正在运行的揽映，然后继续。
WizardSelectDir=选择安装位置
SelectDirDesc=您希望将揽映安装在哪里？
SelectDirLabel3=安装程序会将揽映安装到以下文件夹。您可以保留默认位置，也可以选择其他位置。
WizardSelectTasks=选择附加选项
SelectTasksDesc=按您的使用习惯选择以下选项。
SelectTasksLabel2=不勾选 Windows 集成选项，也可以正常使用揽映。
WizardReady=准备安装
ReadyLabel1=确认以下设置后，点击“安装”开始。
WizardInstalling=正在安装
InstallingLabel=正在安装揽映，请稍候。
FinishedHeadingLabel=揽映安装完成
FinishedLabel=揽映已安装完成，您可以通过开始菜单打开应用。
FinishedLabelNoIcons=揽映已安装完成，您可以打开安装目录中的 Picer.exe。
ClickFinish=点击“完成”退出安装程序。
ButtonBack=上一步(&B)
ButtonNext=下一步(&N)
ButtonInstall=安装(&I)
ButtonFinish=完成(&F)
ButtonCancel=取消
ButtonBrowse=浏览(&B)...
ReadyMemoDir=安装位置：
ReadyMemoTasks=附加选项：
ConfirmUninstall=是否卸载 %1？您的图片、设置和自行安装的插件将保留。
UninstallStatusLabel=正在卸载揽映，请稍候。

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked
Name: "contextmenu"; Description: "加入 Windows 右键菜单（使用揽映打开）"; GroupDescription: "Windows 集成："; Flags: unchecked
Name: "defaultviewer"; Description: "设为默认图片浏览器"; GroupDescription: "Windows 集成："; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "config\*,plugins\*,skins\*,cache\*,logs\*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
#ifndef TestBuild
Name: "{group}\揽映 Picer"; Filename: "{app}\Picer.exe"
Name: "{autodesktop}\揽映 Picer"; Filename: "{app}\Picer.exe"; Tasks: desktopicon
#endif

[Registry]
#include IncludeDir + "\registry.iss"

[Run]
Filename: "ms-settings:defaultapps?registeredAppUser=Picer"; Description: "打开 Windows 默认应用设置，选择揽映"; Tasks: defaultviewer; Flags: shellexec postinstall skipifsilent nowait
Filename: "{app}\Picer.exe"; Description: "启动揽映"; Flags: postinstall skipifsilent nowait

[Code]
const
  RegistryPrefix = '{#RegistryPrefix}';
  FormatList = '{#FormatList}';

procedure SHChangeNotify(EventID: Integer; Flags: Cardinal; Item1, Item2: Integer);
  external 'SHChangeNotify@shell32.dll stdcall';

function OwnCommand(Key: String): Boolean;
var Value: String;
begin
  Result := RegQueryStringValue(HKCU, RegistryPrefix + Key, '', Value) and
    (CompareText(Value, '"' + ExpandConstant('{app}\Picer.exe') + '" "%1"') = 0);
end;

function FormatSuffixes: TArrayOfString;
var Remaining, Suffix: String; Position, Count: Integer;
begin
  Remaining := FormatList;
  SetArrayLength(Result, 0);
  while Remaining <> '' do begin
    Position := Pos(';', Remaining);
    if Position = 0 then begin
      Suffix := Remaining;
      Remaining := '';
    end else begin
      Suffix := Copy(Remaining, 1, Position - 1);
      Delete(Remaining, 1, Position);
    end;
    Count := GetArrayLength(Result);
    SetArrayLength(Result, Count + 1);
    Result[Count] := Suffix;
  end;
end;

procedure CleanupContext;
var Suffixes: TArrayOfString; I: Integer; Key: String; Remaining: Boolean;
begin
  Suffixes := FormatSuffixes;
  Remaining := False;
  for I := 0 to GetArrayLength(Suffixes) - 1 do begin
    Key := 'Software\Classes\SystemFileAssociations\' + Suffixes[I] + '\shell\Picer';
    if OwnCommand(Key + '\command') then
      RegDeleteKeyIncludingSubkeys(HKCU, RegistryPrefix + Key);
    if RegKeyExists(HKCU, RegistryPrefix + Key) then Remaining := True;
  end;
  if not Remaining then
    RegDeleteValue(HKCU, RegistryPrefix + 'Software\Picer', 'ContextExtensions');
end;

procedure CleanupViewer;
var Suffixes: TArrayOfString; I: Integer; Value: String;
begin
  if OwnCommand('Software\Classes\Picer.Image\shell\open\command') then begin
    Suffixes := FormatSuffixes;
    for I := 0 to GetArrayLength(Suffixes) - 1 do
      RegDeleteValue(HKCU, RegistryPrefix + 'Software\Classes\' + Suffixes[I] + '\OpenWithProgids', 'Picer.Image');
    RegDeleteKeyIncludingSubkeys(HKCU, RegistryPrefix + 'Software\Classes\Picer.Image');
  end;
  if OwnCommand('Software\Classes\Applications\Picer.exe\shell\open\command') then
    RegDeleteKeyIncludingSubkeys(HKCU, RegistryPrefix + 'Software\Classes\Applications\Picer.exe');
  if RegQueryStringValue(HKCU, RegistryPrefix + 'Software\Picer\Capabilities', 'ApplicationIcon', Value) and
    (CompareText(Value, '"' + ExpandConstant('{app}\Picer.exe') + '",0') = 0) then begin
    RegDeleteKeyIncludingSubkeys(HKCU, RegistryPrefix + 'Software\Picer\Capabilities');
    if RegQueryStringValue(HKCU, RegistryPrefix + 'Software\RegisteredApplications', 'Picer', Value) and
      (Value = 'Software\Picer\Capabilities') then
      RegDeleteValue(HKCU, RegistryPrefix + 'Software\RegisteredApplications', 'Picer');
  end;
end;

procedure InitializeWizard;
var Notice: TNewStaticText;
begin
  WizardForm.TasksList.Height := WizardForm.TasksList.Height - ScaleY(48);
  Notice := TNewStaticText.Create(WizardForm);
  Notice.Parent := WizardForm.SelectTasksPage;
  Notice.Left := WizardForm.TasksList.Left;
  Notice.Top := WizardForm.TasksList.Top + WizardForm.TasksList.Height + ScaleY(8);
  Notice.Width := WizardForm.TasksList.Width;
  Notice.Height := ScaleY(40);
  Notice.AutoSize := False;
  Notice.WordWrap := True;
  Notice.Caption := '选择默认浏览器后，安装完成时会打开 Windows 默认应用设置，由您确认关联。Windows 11 的右键入口可能位于“显示更多选项”。';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    if not WizardIsTaskSelected('contextmenu') then CleanupContext;
    if not WizardIsTaskSelected('defaultviewer') then CleanupViewer;
    SHChangeNotify($08000000, 0, 0, 0);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then begin
    CleanupContext;
    CleanupViewer;
    SHChangeNotify($08000000, 0, 0, 0);
  end;
end;
