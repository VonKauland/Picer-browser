// Inno's real controls keep keyboard/accessibility and installation behavior.
// Subclass only painting; Windows still owns focus, checks and button input.
const
  SkinBackgroundColor = $232323;
  SkinCardColor = $2E2E2E;
  SkinInputColor = $3B3838;
  SkinAccent = $45FFE2;
  SkinWhite = $F2F2F2;
  SkinMuted = $AAAAAA;
  SkinValidateMessage = $8051;

// Inno Setup 6 runs a 32-bit setup host, including x64 application installs.
type
  TSkinPoint = record X, Y: Integer; end;
  TSkinRect = record Left, Top, Right, Bottom: Integer; end;

function SkinSubclass(Wnd: HWND; Callback: LongInt; Id, Data: LongWord): Boolean;
  external 'SetWindowSubclass@comctl32.dll stdcall';
function SkinUnsubclass(Wnd: HWND; Callback: LongInt; Id: LongWord): Boolean;
  external 'RemoveWindowSubclass@comctl32.dll stdcall';
function SkinDefSubclassProc(Wnd: HWND; Msg: Cardinal; WParam: LongWord; LParam: LongInt): LongInt;
  external 'DefSubclassProc@comctl32.dll stdcall';
function SkinGetDC(Wnd: HWND): LongWord; external 'GetDC@user32.dll stdcall';
function SkinReleaseDC(Wnd: HWND; DC: LongWord): Integer; external 'ReleaseDC@user32.dll stdcall';
function SkinClientRect(Wnd: HWND; var R: TSkinRect): Boolean; external 'GetClientRect@user32.dll stdcall';
function SkinWindowRect(Wnd: HWND; var R: TSkinRect): Boolean; external 'GetWindowRect@user32.dll stdcall';
function SkinCursor(var P: TSkinPoint): Boolean; external 'GetCursorPos@user32.dll stdcall';
function SkinToClient(Wnd: HWND; var P: TSkinPoint): Boolean; external 'ScreenToClient@user32.dll stdcall';
function SkinValidate(Wnd: HWND; R: LongWord): Boolean; external 'ValidateRect@user32.dll stdcall';
function SkinInvalidate(Wnd: HWND; R: LongWord; Erase: Boolean): Boolean;
  external 'InvalidateRect@user32.dll stdcall';
function SkinIsWindow(Wnd: HWND): Boolean; external 'IsWindow@user32.dll stdcall';
function SkinIsEnabled(Wnd: HWND): Boolean; external 'IsWindowEnabled@user32.dll stdcall';
function SkinRoundRegion(L, T, R, B, X, Y: Integer): LongWord;
  external 'CreateRoundRectRgn@gdi32.dll stdcall';
function SkinWindowRegion(Wnd: HWND; Region: LongWord; Redraw: Boolean): Integer;
  external 'SetWindowRgn@user32.dll stdcall';
function SkinDeleteObject(Obj: LongWord): Boolean; external 'DeleteObject@gdi32.dll stdcall';
function SkinTimer(Wnd: HWND; Id: LongWord; Interval: Cardinal; Callback: LongInt): LongWord;
  external 'SetTimer@user32.dll stdcall';
function SkinKillTimer(Wnd: HWND; Id: LongWord): Boolean; external 'KillTimer@user32.dll stdcall';

var
  SkinActive, SkinChoicesReady, SkinInstallPending, SkinPathValidated: Boolean;
  SkinInCallback: Boolean;
  SkinCallback: LongInt;
  SkinControls: array of TWinControl;
  SkinHandles: array of HWND;
  SkinKinds, SkinColors: array of Integer;
  SkinHover: Integer;
  SkinCanvas: TBitmapImage;
  SkinProgress: TBitmapImage;
  SkinHead, SkinSubtitle, SkinPathTitle, SkinUserNote, SkinOptionsTitle: TNewStaticText;
  SkinDefaultNote, SkinProgressTitle, SkinPercent, SkinStatus: TNewStaticText;
  SkinStageOne, SkinStageTwo, SkinStageThree, SkinCompleteTitle, SkinCompletePath: TNewStaticText;
  SkinDesktop, SkinContext, SkinDefault, SkinLaunch: TNewCheckBox;
  SkinClose, SkinFolder: TNewButton;
  SkinLastState, SkinRegionWidth, SkinRegionHeight: Integer;
  SkinCompletePathTitle: TNewStaticText;

function SkinLabel(Parent: TWinControl; Caption: String; X, Y, W, H, Size, Color, Back: Integer): TNewStaticText;
begin
  Result := TNewStaticText.Create(WizardForm);
  Result.Parent := Parent;
  Result.AutoSize := False;
  Result.ShowAccelChar := False;
  Result.SetBounds(ScaleX(X), ScaleY(Y), ScaleX(W), ScaleY(H));
  Result.Caption := Caption;
  Result.Font.Assign(WizardForm.Font);
  Result.Font.Size := Size;
  Result.Font.Color := Color;
  Result.Color := Back;
end;

procedure SkinPaint(Index: Integer; DC: LongWord);
var C: TCanvas; R: TSkinRect; Caption: String;
    W, H, BoxSize, Y, X, Ink, Fill, Edge: Integer; Hover, Checked: Boolean;
begin
  if (Index < 0) or (Index >= GetArrayLength(SkinHandles)) then Exit;
  SkinClientRect(SkinHandles[Index], R);
  W := R.Right; H := R.Bottom;
  C := TCanvas.Create;
  try
    C.Handle := DC;
    C.Brush.Color := SkinColors[Index];
    C.Pen.Style := psClear;
    C.Rectangle(0, 0, W, H);
    C.Font.Assign(WizardForm.Font);
    C.Font.Size := 10;
    Hover := SkinHover = Index;
    Ink := SkinWhite;
    if not SkinIsEnabled(SkinHandles[Index]) then Ink := $777777;
    C.Font.Color := Ink;
    if SkinKinds[Index] = 2 then begin
      Caption := TNewCheckBox(SkinControls[Index]).Caption;
      StringChangeEx(Caption, '&', '', True);
      Checked := SendMessage(SkinHandles[Index], $00F0, 0, 0) = 1;
      BoxSize := ScaleX(19); Y := (H - BoxSize) div 2; X := ScaleX(2);
      C.Pen.Style := psSolid;
      C.Pen.Color := $666666;
      C.Brush.Color := SkinColors[Index];
      if Checked then begin C.Brush.Color := SkinAccent; C.Pen.Color := SkinAccent; end;
      if SkinControls[Index].Focused then C.Pen.Color := SkinAccent;
      C.RoundRect(X, Y, X + BoxSize, Y + BoxSize, ScaleX(6), ScaleY(6));
      if Checked then begin
        C.Pen.Color := SkinBackgroundColor; C.Pen.Width := ScaleX(2);
        C.MoveTo(X + ScaleX(4), Y + ScaleY(9));
        C.LineTo(X + ScaleX(8), Y + ScaleY(13));
        C.LineTo(X + ScaleX(15), Y + ScaleY(5));
      end;
      C.Brush.Style := bsClear;
      C.TextOut(ScaleX(30), (H - C.TextHeight(Caption)) div 2, Caption);
    end else begin
      Caption := TNewButton(SkinControls[Index]).Caption;
      StringChangeEx(Caption, '&', '', True);
      Fill := $3B3838; Edge := $48484C;
      if Hover then Fill := $484448;
      if SkinKinds[Index] = 1 then begin
        Fill := SkinAccent; Edge := SkinAccent; C.Font.Color := SkinBackgroundColor;
        C.Font.Style := [fsBold];
        if Hover then Fill := $77FFEA;
      end;
      if not SkinIsEnabled(SkinHandles[Index]) then begin Fill := $343434; C.Font.Color := $777777; end;
      if SkinControls[Index].Focused then Edge := SkinAccent;
      C.Brush.Color := Fill; C.Pen.Style := psSolid; C.Pen.Color := Edge; C.Pen.Width := ScaleX(1);
      C.RoundRect(1, 1, W - 1, H - 1, H - 2, H - 2);
      C.Brush.Style := bsClear;
      if SkinKinds[Index] = 3 then begin
        C.Pen.Color := SkinWhite; C.Pen.Width := ScaleX(1);
        X := W div 2; Y := H div 2;
        C.MoveTo(X - ScaleX(5), Y - ScaleY(5)); C.LineTo(X + ScaleX(5), Y + ScaleY(5));
        C.MoveTo(X + ScaleX(5), Y - ScaleY(5)); C.LineTo(X - ScaleX(5), Y + ScaleY(5));
      end else
        C.TextOut((W - C.TextWidth(Caption)) div 2, (H - C.TextHeight(Caption)) div 2, Caption);
    end;
  finally
    C.Handle := 0;
    C.Free;
  end;
end;

procedure SkinRoundWindow;
var Region: LongWord;
begin
  if (SkinRegionWidth = WizardForm.Width) and (SkinRegionHeight = WizardForm.Height) then Exit;
  SkinRegionWidth := WizardForm.Width; SkinRegionHeight := WizardForm.Height;
  Region := SkinRoundRegion(0, 0, WizardForm.Width, WizardForm.Height, ScaleX(40), ScaleY(40));
  if SkinWindowRegion(WizardForm.Handle, Region, True) = 0 then SkinDeleteObject(Region);
end;

function SkinWindowProc(Wnd: HWND; Msg: Cardinal; WParam: LongWord;
  LParam: LongInt; Id, Data: LongWord): LongInt;
var DC: LongWord; P: TSkinPoint; R: TSkinRect; I, Hover: Integer;
begin
  { Native button input can synchronously send more window messages. Avoid
    re-entering the script painter while VCL is already dispatching input. }
  if SkinInCallback then begin
    Result := SkinDefSubclassProc(Wnd, Msg, WParam, LParam); Exit;
  end;
  SkinInCallback := True;
  try
    try
  if Msg = $0082 then begin
    SkinUnsubclass(Wnd, SkinCallback, 1);
    Result := SkinDefSubclassProc(Wnd, Msg, WParam, LParam);
    Exit;
  end;
  if Data > 0 then begin
    if (Msg = $000F) or (Msg = $0318) then begin
      if Msg = $000F then DC := SkinGetDC(Wnd) else DC := WParam;
      SkinPaint(Data - 1, DC);
      if Msg = $000F then begin SkinReleaseDC(Wnd, DC); SkinValidate(Wnd, 0); end;
      Result := 0; Exit;
    end;
    if Msg = $0014 then begin Result := 1; Exit; end;
    Result := SkinDefSubclassProc(Wnd, Msg, WParam, LParam);
    if (Msg = $00F1) or (Msg = $0007) or (Msg = $0008) or (Msg = $000A) then
      SkinInvalidate(Wnd, 0, False);
    Exit;
  end;
  if Msg = SkinValidateMessage then begin
    WizardForm.BackButton.OnClick(WizardForm.BackButton);
    Result := 0; Exit;
  end;
  if Msg = $0084 then begin
    SkinCursor(P); SkinToClient(Wnd, P);
    if (P.Y < ScaleY(58)) and (P.X > ScaleX(60)) and
       (P.X < WizardForm.ClientWidth - ScaleX(65)) then begin Result := 2; Exit; end;
  end;
  if (Msg = $0113) and (WParam = 73) then begin
    Hover := -1; SkinCursor(P);
    for I := 0 to GetArrayLength(SkinHandles) - 1 do
      if SkinIsWindow(SkinHandles[I]) and SkinControls[I].Showing then begin
        SkinWindowRect(SkinHandles[I], R);
        if (P.X >= R.Left) and (P.X < R.Right) and (P.Y >= R.Top) and (P.Y < R.Bottom) then Hover := I;
      end;
    if Hover <> SkinHover then begin
      if SkinHover >= 0 then SkinInvalidate(SkinHandles[SkinHover], 0, False);
      SkinHover := Hover;
      if SkinHover >= 0 then SkinInvalidate(SkinHandles[SkinHover], 0, False);
    end;
    Result := 0; Exit;
  end;
  Result := SkinDefSubclassProc(Wnd, Msg, WParam, LParam);
  if Msg = $0005 then SkinRoundWindow;
    except
      Log('Installer UI callback failed, message ' + IntToStr(Msg) + ': ' + GetExceptionMessage);
      Result := SkinDefSubclassProc(Wnd, Msg, WParam, LParam);
    end;
  finally
    SkinInCallback := False;
  end;
end;

procedure SkinControl(Control: TWinControl; Kind, Back: Integer);
var I: Integer;
begin
  I := GetArrayLength(SkinHandles);
  SetArrayLength(SkinHandles, I + 1); SetArrayLength(SkinControls, I + 1);
  SetArrayLength(SkinKinds, I + 1); SetArrayLength(SkinColors, I + 1);
  SkinHandles[I] := Control.Handle; SkinControls[I] := Control;
  SkinKinds[I] := Kind; SkinColors[I] := Back;
  if not SkinSubclass(Control.Handle, SkinCallback, 1, I + 1) then
    RaiseException('Unable to initialize installer controls');
end;

function SkinCheck(Caption: String; X, Y, W, Back: Integer): TNewCheckBox;
begin
  Result := TNewCheckBox.Create(WizardForm); Result.Parent := WizardForm;
  Result.SetBounds(ScaleX(X), ScaleY(Y), ScaleX(W), ScaleY(32));
  Result.Caption := Caption; Result.Color := Back;
  Result.Font.Assign(WizardForm.Font); Result.Font.Color := SkinWhite;
  SkinControl(Result, 2, Back);
end;

procedure SkinAbout(Sender: TObject);
begin
  { Preserve Inno Setup's original About box and its text. }
  SendMessage(WizardForm.Handle, $0112, 9999, 0);
end;

procedure SkinCloseClick(Sender: TObject);
begin
  if WizardForm.CurPageID = wpFinished then
    WizardForm.NextButton.OnClick(WizardForm.NextButton)
  else WizardForm.CancelButton.OnClick(WizardForm.CancelButton);
end;

procedure SkinFolderClick(Sender: TObject);
var Code: Integer;
begin
  ShellExec('open', ExpandConstant('{app}'), '', '', SW_SHOWNORMAL, ewNoWait, Code);
end;

procedure SkinDrawProgress(Value: Integer);
var W, H, Fill: Integer;
begin
  if not SkinActive then Exit;
  W := SkinProgress.Width; H := SkinProgress.Height;
  SkinProgress.Bitmap.Width := W; SkinProgress.Bitmap.Height := H;
  SkinProgress.Bitmap.Canvas.Brush.Color := SkinCardColor;
  SkinProgress.Bitmap.Canvas.Pen.Style := psClear;
  SkinProgress.Bitmap.Canvas.Rectangle(0, 0, W, H);
  SkinProgress.Bitmap.Canvas.Brush.Color := $454549;
  SkinProgress.Bitmap.Canvas.RoundRect(0, 0, W, H, H, H);
  Fill := (W * Value) div 100;
  if Fill > 0 then begin
    SkinProgress.Bitmap.Canvas.Brush.Color := SkinAccent;
    SkinProgress.Bitmap.Canvas.RoundRect(0, 0, Fill, H, H, H);
  end;
  SkinPercent.Caption := IntToStr(Value) + '%';
  SkinProgress.Invalidate;
end;

procedure SkinState(State: Integer);
var Setup, Progress, Finished: Boolean;
begin
  if not SkinActive then Exit;
  Setup := State = 0; Progress := State = 1; Finished := State = 2;
  WizardForm.OuterNotebook.Visible := False;
  WizardForm.InnerNotebook.Visible := False;
  WizardForm.BackButton.Visible := False;
  if State <> SkinLastState then begin
    if Setup then SkinCanvas.Bitmap.LoadFromFile(ExpandConstant('{tmp}\installer-setup.bmp'))
    else if Progress then SkinCanvas.Bitmap.LoadFromFile(ExpandConstant('{tmp}\installer-progress.bmp'))
    else SkinCanvas.Bitmap.LoadFromFile(ExpandConstant('{tmp}\installer-finished.bmp'));
    SkinLastState := State;
  end;
  SkinHead.Left := ScaleX(330); SkinSubtitle.Left := ScaleX(330);
  if Setup then begin
    SkinHead.Caption := '安装揽映'; SkinSubtitle.Caption := '选择安装位置与附加选项';
    WizardForm.NextButton.Caption := '安装';
    WizardForm.CancelButton.Caption := '取消';
  end else if Progress then begin
    SkinHead.Caption := '正在安装揽映'; SkinSubtitle.Caption := '正在将揽映安装到此电脑。';
    WizardForm.CancelButton.Caption := '取消安装';
  end else begin
    SkinHead.Caption := '安装完成'; SkinSubtitle.Caption := '揽映已成功安装到此电脑。';
    SkinHead.Left := ScaleX(394); SkinSubtitle.Left := ScaleX(394);
    WizardForm.NextButton.Caption := '完成';
    SkinCompletePath.Caption := WizardDirValue;
    SkinCompletePath.Hint := WizardDirValue; SkinCompletePath.ShowHint := True;
  end;
  WizardForm.DirEdit.Visible := Setup; WizardForm.DirBrowseButton.Visible := Setup;
  SkinPathTitle.Visible := Setup; SkinUserNote.Visible := Setup; SkinOptionsTitle.Visible := Setup;
  SkinDefaultNote.Visible := Setup;
  SkinDesktop.Visible := Setup; SkinContext.Visible := Setup; SkinDefault.Visible := Setup;
  SkinLaunch.Visible := not Progress;
  if Finished then SkinLaunch.Caption := '立即启动揽映'
  else SkinLaunch.Caption := '安装完成后启动揽映';
  SkinProgress.Visible := Progress; SkinProgressTitle.Visible := Progress;
  SkinPercent.Visible := Progress; SkinStatus.Visible := Progress;
  SkinStageOne.Visible := Progress; SkinStageTwo.Visible := Progress; SkinStageThree.Visible := Progress;
  SkinCompleteTitle.Visible := Finished; SkinCompletePath.Visible := Finished; SkinFolder.Visible := Finished;
  SkinCompletePathTitle.Visible := Finished;
  WizardForm.NextButton.Visible := not Progress;
  WizardForm.CancelButton.Visible := not Finished;
  if Progress then WizardForm.CancelButton.Left := ScaleX(840)
  else WizardForm.CancelButton.Left := ScaleX(734);
  SkinRoundWindow;
end;

procedure InitializeInstallerSkin;
var I: Integer; LabelControl: TNewStaticText; Hotspot: TLabel;
begin
  SkinActive := not WizardSilent;
  if not SkinActive then Exit;
  SkinLastState := -1; SkinHover := -1;
  WizardForm.BorderStyle := bsNone;
  WizardForm.Caption := '揽映 Picer 安装程序';
  WizardForm.Color := SkinBackgroundColor;
  WizardForm.Font.Name := 'Microsoft YaHei UI'; WizardForm.Font.Size := 9;
  WizardForm.ClientWidth := ScaleX(1000); WizardForm.ClientHeight := ScaleY(640);
  WizardForm.Position := poScreenCenter;
  for I := 0 to WizardForm.ControlCount - 1 do WizardForm.Controls[I].Visible := False;
  ExtractTemporaryFile('installer-setup.bmp');
  ExtractTemporaryFile('installer-progress.bmp');
  ExtractTemporaryFile('installer-finished.bmp');
  SkinCanvas := TBitmapImage.Create(WizardForm); SkinCanvas.Parent := WizardForm;
  SkinCanvas.Align := alClient; SkinCanvas.Stretch := True; SkinCanvas.SendToBack;
  SkinCallback := CreateCallback(@SkinWindowProc);
  SkinSubclass(WizardForm.Handle, SkinCallback, 1, 0);
  SkinTimer(WizardForm.Handle, 73, 80, 0);
  LabelControl := SkinLabel(WizardForm, '揽映 Picer 安装程序', 66, 18, 400, 28, 12, SkinWhite, SkinBackgroundColor);
  Hotspot := TLabel.Create(WizardForm); Hotspot.Parent := WizardForm;
  Hotspot.AutoSize := False;
  Hotspot.SetBounds(ScaleX(19), ScaleY(9), ScaleX(40), ScaleY(40));
  Hotspot.Transparent := True; Hotspot.Caption := ''; Hotspot.Cursor := crHandPoint;
  Hotspot.Hint := '关于安装程序'; Hotspot.ShowHint := True; Hotspot.OnClick := @SkinAbout;
  LabelControl := SkinLabel(WizardForm, '揽映 Picer', 42, 362, 235, 58, 26, SkinWhite, SkinBackgroundColor);
  LabelControl.Alignment := taCenter;
  LabelControl := SkinLabel(WizardForm, '揽景入方寸' + #13#10 + '映眸见万象', 52, 435, 214, 62, 14, SkinMuted, SkinBackgroundColor);
  LabelControl.Alignment := taCenter;
  LabelControl := SkinLabel(WizardForm, 'Windows x64', 34, 594, 94, 20, 9, SkinMuted, $2F2C2C);
  LabelControl.Alignment := taCenter;
  SkinHead := SkinLabel(WizardForm, '', 330, 90, 610, 48, 25, SkinWhite, SkinBackgroundColor);
  SkinHead.Font.Style := [fsBold];
  SkinSubtitle := SkinLabel(WizardForm, '', 330, 140, 610, 28, 12, SkinMuted, SkinBackgroundColor);
  SkinPathTitle := SkinLabel(WizardForm, '安装位置', 350, 190, 400, 27, 13, SkinWhite, SkinCardColor);
  SkinUserNote := SkinLabel(WizardForm, '仅为当前用户安装', 350, 274, 550, 22, 10, SkinMuted, SkinCardColor);
  SkinOptionsTitle := SkinLabel(WizardForm, '安装选项', 350, 338, 400, 28, 13, SkinWhite, SkinCardColor);
  SkinDesktop := SkinCheck('创建桌面快捷方式', 350, 378, 550, SkinCardColor);
  SkinContext := SkinCheck('加入 Windows 右键菜单', 350, 415, 550, SkinCardColor);
  SkinDefault := SkinCheck('设为默认图片浏览器', 350, 452, 550, SkinCardColor);
  SkinDefaultNote := SkinLabel(WizardForm, '安装后在 Windows 设置中确认', 380, 488, 540, 22, 10, SkinMuted, SkinCardColor);
  SkinLaunch := SkinCheck('安装完成后启动揽映', 330, 574, 374, SkinBackgroundColor);
  SkinLaunch.Checked := True;
  WizardForm.DirEdit.Parent := WizardForm;
  WizardForm.DirEdit.SetBounds(ScaleX(362), ScaleY(234), ScaleX(460), ScaleY(25));
  WizardForm.DirEdit.BorderStyle := bsNone; WizardForm.DirEdit.Color := SkinInputColor;
  WizardForm.DirEdit.Font.Assign(WizardForm.Font); WizardForm.DirEdit.Font.Size := 10;
  WizardForm.DirEdit.Font.Color := SkinWhite;
  WizardForm.DirBrowseButton.Parent := WizardForm;
  WizardForm.DirBrowseButton.SetBounds(ScaleX(848), ScaleY(222), ScaleX(102), ScaleY(42));
  WizardForm.DirBrowseButton.Caption := '浏览';
  SkinControl(WizardForm.DirBrowseButton, 0, SkinCardColor);
  WizardForm.NextButton.SetBounds(ScaleX(840), ScaleY(574), ScaleX(130), ScaleY(44));
  WizardForm.CancelButton.SetBounds(ScaleX(734), ScaleY(574), ScaleX(94), ScaleY(44));
  SkinControl(WizardForm.NextButton, 1, SkinBackgroundColor);
  SkinControl(WizardForm.CancelButton, 0, SkinBackgroundColor);
  SkinClose := TNewButton.Create(WizardForm); SkinClose.Parent := WizardForm;
  SkinClose.SetBounds(ScaleX(948), ScaleY(13), ScaleX(32), ScaleY(32));
  SkinClose.Caption := '关闭'; SkinClose.OnClick := @SkinCloseClick;
  SkinControl(SkinClose, 3, SkinBackgroundColor);
  SkinProgressTitle := SkinLabel(WizardForm, '安装进度', 358, 208, 400, 30, 14, SkinWhite, SkinCardColor);
  SkinPercent := SkinLabel(WizardForm, '0%', 850, 205, 90, 40, 22, SkinAccent, SkinCardColor);
  SkinPercent.Alignment := taRightJustify;
  SkinProgress := TBitmapImage.Create(WizardForm); SkinProgress.Parent := WizardForm;
  SkinProgress.SetBounds(ScaleX(358), ScaleY(264), ScaleX(584), ScaleY(16));
  SkinStatus := SkinLabel(WizardForm, '正在安装文件…', 358, 297, 580, 28, 12, SkinMuted, SkinCardColor);
  SkinStageOne := SkinLabel(WizardForm, '✓   准备安装', 358, 356, 540, 30, 13, SkinAccent, SkinCardColor);
  SkinStageTwo := SkinLabel(WizardForm, '◌   安装文件', 358, 399, 540, 30, 13, SkinWhite, SkinCardColor);
  SkinStageThree := SkinLabel(WizardForm, '○   完成配置', 358, 442, 540, 30, 13, SkinMuted, SkinCardColor);
  SkinCompleteTitle := SkinLabel(WizardForm, '可以开始浏览图片了', 358, 250, 580, 36, 16, SkinWhite, SkinCardColor);
  SkinCompleteTitle.Font.Style := [fsBold];
  SkinCompletePathTitle := SkinLabel(WizardForm, '安装位置', 358, 310, 580, 25, 11, SkinMuted, SkinCardColor);
  SkinCompletePath := SkinLabel(WizardForm, '', 358, 342, 580, 44, 11, SkinWhite, SkinCardColor);
  SkinCompletePath.WordWrap := True;
  SkinFolder := TNewButton.Create(WizardForm); SkinFolder.Parent := WizardForm;
  SkinFolder.SetBounds(ScaleX(358), ScaleY(395), ScaleX(165), ScaleY(42));
  SkinFolder.Caption := '打开安装目录'; SkinFolder.OnClick := @SkinFolderClick;
  SkinControl(SkinFolder, 0, SkinCardColor);
  WizardForm.InnerNotebook.Parent := WizardForm;
  WizardForm.InnerNotebook.SetBounds(ScaleX(350), ScaleY(190), ScaleX(596), ScaleY(320));
  SkinState(0); SkinDrawProgress(0);
end;

procedure InstallerPageChanged(Page: Integer);
begin
  if not SkinActive then Exit;
  if Page = wpSelectDir then begin
    SkinState(0);
    if not SkinChoicesReady or SkinInstallPending then
      PostMessage(WizardForm.NextButton.Handle, $00F5, 0, 0);
  end else if Page = wpSelectTasks then begin
    SkinState(0);
    if not SkinChoicesReady then begin
      SkinDesktop.Checked := WizardIsTaskSelected('desktopicon');
      SkinContext.Checked := WizardIsTaskSelected('contextmenu');
      SkinDefault.Checked := WizardIsTaskSelected('defaultviewer');
      SkinChoicesReady := True;
    end else if SkinInstallPending then begin
      SkinPathValidated := True; SkinInstallPending := False;
      PostMessage(WizardForm.NextButton.Handle, $00F5, 0, 0);
    end;
  end else if Page = wpFinished then SkinState(2)
  else begin
    SkinState(1);
    if Page <> wpInstalling then begin
      { Keep native file-in-use/error pages accessible, rather than hiding them. }
      SkinProgress.Visible := False; SkinPercent.Visible := False; SkinStatus.Visible := False;
      SkinProgressTitle.Visible := False;
      SkinStageOne.Visible := False; SkinStageTwo.Visible := False; SkinStageThree.Visible := False;
      WizardForm.InnerNotebook.Visible := True;
      WizardForm.NextButton.Visible := WizardForm.NextButton.Enabled;
    end;
  end;
end;

procedure SkinSaveTasks;
var Tasks: String;
begin
  Tasks := '!desktopicon,!contextmenu,!defaultviewer';
  if SkinDesktop.Checked then Tasks := Tasks + ',desktopicon';
  if SkinContext.Checked then Tasks := Tasks + ',contextmenu';
  if SkinDefault.Checked then Tasks := Tasks + ',defaultviewer';
  WizardSelectTasks(Tasks);
end;

function InstallerNext(Page: Integer): Boolean;
var I: Integer;
begin
  Result := True;
  if not SkinActive then Exit;
  if (Page = wpSelectDir) and SkinChoicesReady then begin
    SkinSaveTasks; SkinInstallPending := True;
  end else if Page = wpSelectTasks then begin
    SkinSaveTasks;
    if not SkinPathValidated then begin
      SkinInstallPending := True;
      PostMessage(WizardForm.Handle, SkinValidateMessage, 0, 0);
      Result := False;
    end else SkinPathValidated := False;
  end else if Page = wpFinished then
    for I := 0 to WizardForm.RunList.Items.Count - 1 do
      if WizardForm.RunList.Items[I] = '启动揽映' then
        WizardForm.RunList.Checked[I] := SkinLaunch.Checked;
end;

procedure InstallerProgress(Current, Maximum: Integer);
var Value: Integer;
begin
  if not SkinActive or (Maximum <= 0) then Exit;
  Value := (Int64(Current) * 100) div Maximum;
  if Value > 100 then Value := 100;
  if Value < 0 then Value := 0;
  SkinDrawProgress(Value);
end;

procedure DeinitializeInstallerSkin;
var I: Integer;
begin
  if not SkinActive then Exit;
  SkinKillTimer(WizardForm.Handle, 73);
  for I := 0 to GetArrayLength(SkinHandles) - 1 do
    if SkinIsWindow(SkinHandles[I]) then SkinUnsubclass(SkinHandles[I], SkinCallback, 1);
  if SkinIsWindow(WizardForm.Handle) then SkinUnsubclass(WizardForm.Handle, SkinCallback, 1);
  SkinActive := False;
end;
