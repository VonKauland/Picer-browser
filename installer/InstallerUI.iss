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

#include IncludeDir + "\InstallerGraphics.iss"

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
function SkinInvalidate(Wnd: HWND; R: LongWord; Erase: Boolean): Boolean;
  external 'InvalidateRect@user32.dll stdcall';
function SkinIsWindow(Wnd: HWND): Boolean; external 'IsWindow@user32.dll stdcall';
function SkinIsEnabled(Wnd: HWND): Boolean; external 'IsWindowEnabled@user32.dll stdcall';
function SkinBlit(Dest: LongWord; X, Y, W, H: Integer; Source: LongWord;
  SX, SY: Integer; Operation: LongWord): Boolean;
  external 'BitBlt@gdi32.dll stdcall';
function SkinTimer(Wnd: HWND; Id: LongWord; Interval: Cardinal; Callback: LongInt): LongWord;
  external 'SetTimer@user32.dll stdcall';
function SkinKillTimer(Wnd: HWND; Id: LongWord): Boolean; external 'KillTimer@user32.dll stdcall';

var
  SkinActive, SkinChoicesReady, SkinInstallPending, SkinPathValidated: Boolean;
  SkinCallback: LongInt;
  SkinControls: array of TWinControl;
  SkinHandles: array of HWND;
  SkinKinds, SkinColors: array of Integer;
  SkinPressed: array of Boolean;
  SkinHover: Integer;
  SkinCanvas: TBitmapImage;
  SkinProgress: TBitmapImage;
  SkinHead, SkinSubtitle, SkinPathTitle, SkinUserNote, SkinOptionsTitle: TNewStaticText;
  SkinDefaultNote, SkinProgressTitle, SkinPercent, SkinStatus: TNewStaticText;
  SkinStageOne, SkinStageTwo, SkinStageThree, SkinCompleteTitle, SkinCompletePath: TNewStaticText;
  SkinDesktop, SkinContext, SkinDefault, SkinLaunch: TNewCheckBox;
  SkinClose, SkinFolder: TNewButton;
  SkinLastState: Integer;
  SkinStageMarks: array of TBitmapImage;
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
var C: TCanvas; Surface: TBitmap; R: TSkinRect; Caption: String; Graphics: LongWord;
    W, H, BoxSize, Y, X, Ink, Fill, Edge: Integer; Hover, Checked, Enabled, Focused, Pressed: Boolean;
begin
  if (Index < 0) or (Index >= GetArrayLength(SkinHandles)) then Exit;
  SkinClientRect(SkinHandles[Index], R);
  W := R.Right; H := R.Bottom;
  if (W <= 0) or (H <= 0) or (DC = 0) then Exit;
  Surface := TBitmap.Create;
  try
    Surface.Width := W; Surface.Height := H; C := Surface.Canvas;
    SkinClear(C.Handle, W, H, SkinColors[Index]);
    Hover := SkinHover = Index;
    Enabled := SkinIsEnabled(SkinHandles[Index]);
    Focused := SkinControls[Index].Focused;
    Ink := SkinWhite;
    if not Enabled then Ink := $777777;
    { Read native state before a drawing context exists. Sending BM_GETSTATE
      during GDI+ drawing can re-enter the script callback and lose the context. }
    if SkinKinds[Index] = 2 then begin
      Caption := TNewCheckBox(SkinControls[Index]).Caption;
      Checked := TNewCheckBox(SkinControls[Index]).Checked;
    end else Caption := TNewButton(SkinControls[Index]).Caption;
    Pressed := SkinPressed[Index];
    Graphics := SkinGraphics(C.Handle);
    try
      if SkinKinds[Index] = 2 then begin
        BoxSize := ScaleX(19); Y := (H - BoxSize) div 2; X := ScaleX(2);
        Fill := SkinColors[Index]; Edge := $666666;
        if Checked then begin Fill := SkinAccent; Edge := SkinAccent; end;
        if Focused or Hover then Edge := SkinAccent;
        SkinRounded(Graphics, X + 0.5, Y + 0.5, BoxSize - 1, BoxSize - 1, ScaleX(4), Fill, Edge, ScaleX(1));
        if Checked then begin
          SkinLine(Graphics, SkinBackgroundColor, ScaleX(2), X + ScaleX(4), Y + ScaleY(9), X + ScaleX(8), Y + ScaleY(13));
          SkinLine(Graphics, SkinBackgroundColor, ScaleX(2), X + ScaleX(8), Y + ScaleY(13), X + ScaleX(15), Y + ScaleY(5));
        end;
      end else begin
        Fill := $3B3838; Edge := $48484C;
        if Hover then Fill := $484448;
        if SkinKinds[Index] = 1 then begin
          Fill := SkinAccent; Edge := SkinAccent; Ink := SkinBackgroundColor;
          if Hover then Fill := $77FFEA;
          if Pressed then Fill := $34DAC5;
        end else if Pressed then Fill := $302E30;
        if not Enabled then begin Fill := $343434; Ink := $777777; end;
        if Focused then Edge := SkinAccent;
        SkinRounded(Graphics, 1, 1, W - 2, H - 2, (H - 2) / 2, Fill, Edge, ScaleX(1));
        if SkinKinds[Index] = 3 then begin
          X := W div 2; Y := H div 2;
          SkinLine(Graphics, Ink, ScaleX(1), X - ScaleX(5), Y - ScaleY(5), X + ScaleX(5), Y + ScaleY(5));
          SkinLine(Graphics, Ink, ScaleX(1), X + ScaleX(5), Y - ScaleY(5), X - ScaleX(5), Y + ScaleY(5));
        end;
      end;
    finally
      SkinGdiDeleteGraphics(Graphics);
    end;
    StringChangeEx(Caption, '&', '', True);
    C.Font.Assign(WizardForm.Font); C.Font.Size := 10; C.Font.Color := Ink;
    if SkinKinds[Index] = 1 then C.Font.Style := [fsBold];
    C.Brush.Style := bsClear;
    if SkinKinds[Index] = 2 then
      C.TextOut(ScaleX(30), (H - C.TextHeight(Caption)) div 2, Caption)
    else if SkinKinds[Index] <> 3 then
      C.TextOut((W - C.TextWidth(Caption)) div 2, (H - C.TextHeight(Caption)) div 2, Caption);
    SkinBlit(DC, 0, 0, W, H, C.Handle, 0, 0, $00CC0020);
  finally
    Surface.Free;
  end;
end;

procedure SkinPaintBackground;
var Graphics: LongWord;
begin
  if (SkinLastState < 0) or (SkinGraphicsToken = 0) then Exit;
  SkinCanvas.Bitmap.Width := WizardForm.ClientWidth;
  SkinCanvas.Bitmap.Height := WizardForm.ClientHeight;
  Graphics := SkinGraphics(SkinCanvas.Bitmap.Canvas.Handle);
  try
    SkinGdiDrawImage(Graphics, SkinBackgroundImages[SkinLastState], 0, 0,
      SkinCanvas.Bitmap.Width, SkinCanvas.Bitmap.Height);
  finally
    SkinGdiDeleteGraphics(Graphics);
  end;
  SkinCanvas.Invalidate;
end;

function SkinWindowProc(Wnd: HWND; Msg: Cardinal; WParam: LongWord;
  LParam: LongInt; Id, Data: LongWord): LongInt;
var DC: LongWord; Info: TSkinPaintInfo; P: TSkinPoint; R: TSkinRect; I, Hover: Integer;
begin
  try
    if Msg = $0082 then begin
      SkinUnsubclass(Wnd, SkinCallback, 1);
      Result := SkinDefSubclassProc(Wnd, Msg, WParam, LParam); Exit;
    end;
    if Data > 0 then begin
      { Always handle child paint, even inside native input/parent painting.
        Falling back here exposes the white themed button/checkbox frame. }
      if (Msg = $000F) or (Msg = $0317) or (Msg = $0318) then begin
        if Msg = $000F then DC := SkinBeginPaint(Wnd, Info) else DC := WParam;
        try SkinPaint(Data - 1, DC);
        finally if Msg = $000F then SkinEndPaint(Wnd, Info); end;
        Result := 0; Exit;
      end;
      if (Msg = $0014) or (Msg = $0085) then begin Result := 1; Exit; end;
      if Msg = $00F3 then SkinPressed[Data - 1] := WParam <> 0;
      Result := SkinDefSubclassProc(Wnd, Msg, WParam, LParam);
      if (Msg = $00F1) or (Msg = $00F3) or (Msg = $00F4) or
         (Msg = $0007) or (Msg = $0008) or (Msg = $000A) then begin
        DC := SkinGetDC(Wnd);
        try SkinPaint(Data - 1, DC); finally SkinReleaseDC(Wnd, DC); end;
      end;
      Exit;
    end;
    if (Msg = $0083) and SkinNativeFrameReady then begin Result := 0; Exit; end;
    if (Msg = $0112) and (((WParam and $FFF0) = $F000) or ((WParam and $FFF0) = $F030)) then begin
      Result := 0; Exit; { Fixed installer size, even though DWM needs a thick-frame style. }
    end;
    if Msg = SkinValidateMessage then begin
      WizardForm.BackButton.OnClick(WizardForm.BackButton); Result := 0; Exit;
    end;
    if (Msg = $0084) and SkinNativeFrameReady then begin
      SkinCursor(P); SkinToClient(Wnd, P);
      if (P.Y >= 0) and (P.Y < ScaleY(58)) and (P.X > ScaleX(60)) and
         (P.X < WizardForm.ClientWidth - ScaleX(65)) then Result := 2 else Result := 1;
      Exit;
    end;
    if (Msg = $0113) and (WParam = 73) then begin
      Hover := -1; SkinCursor(P);
      for I := 0 to GetArrayLength(SkinHandles) - 1 do
        if SkinIsWindow(SkinHandles[I]) and SkinControls[I].Showing then begin
          SkinWindowRect(SkinHandles[I], R);
          if (P.X >= R.Left) and (P.X < R.Right) and (P.Y >= R.Top) and (P.Y < R.Bottom) then Hover := I;
        end;
      if Hover <> SkinHover then begin
        I := SkinHover; SkinHover := Hover;
        if I >= 0 then SkinInvalidate(SkinHandles[I], 0, False);
        if Hover >= 0 then SkinInvalidate(SkinHandles[Hover], 0, False);
      end;
      Result := 0; Exit;
    end;
    Result := SkinDefSubclassProc(Wnd, Msg, WParam, LParam);
    if (Msg = $0005) and (SkinLastState >= 0) then SkinPaintBackground;
  except
    Log('Installer UI callback failed, message ' + IntToStr(Msg) + ': ' + GetExceptionMessage);
    if (Data > 0) and ((Msg = $000F) or (Msg = $0317) or (Msg = $0318)) then Result := 0
    else Result := SkinDefSubclassProc(Wnd, Msg, WParam, LParam);
  end;
end;

procedure SkinControl(Control: TWinControl; Kind, Back: Integer);
var I: Integer;
begin
  I := GetArrayLength(SkinHandles);
  SetArrayLength(SkinHandles, I + 1); SetArrayLength(SkinControls, I + 1);
  SetArrayLength(SkinKinds, I + 1); SetArrayLength(SkinColors, I + 1);
  SetArrayLength(SkinPressed, I + 1);
  SkinHandles[I] := Control.Handle; SkinControls[I] := Control;
  SkinKinds[I] := Kind; SkinColors[I] := Back;
  SkinWindowTheme(Control.Handle, '', '');
  SkinSetWindowLong(Control.Handle, -16, SkinGetWindowLong(Control.Handle, -16) and not $00C00000);
  SkinSetWindowLong(Control.Handle, -20, SkinGetWindowLong(Control.Handle, -20) and not $00020200);
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
var W, H, Fill: Integer; Graphics: LongWord;
begin
  if not SkinActive then Exit;
  W := SkinProgress.Width; H := SkinProgress.Height;
  SkinProgress.Bitmap.Width := W; SkinProgress.Bitmap.Height := H;
  SkinClear(SkinProgress.Bitmap.Canvas.Handle, W, H, SkinCardColor);
  Graphics := SkinGraphics(SkinProgress.Bitmap.Canvas.Handle);
  try
    SkinRounded(Graphics, 1, 1, W - 2, H - 2, H / 2, $454549, $454549, 0);
    Fill := ((W - 2) * Value) div 100;
    if Fill > 0 then SkinRounded(Graphics, 1, 1, Fill, H - 2, H / 2, SkinAccent, SkinAccent, 0);
  finally
    SkinGdiDeleteGraphics(Graphics);
  end;
  SkinPercent.Caption := IntToStr(Value) + '%'; SkinProgress.Invalidate;
end;

procedure SkinDrawStages(Active: Integer);
var I, W, H, Color: Integer; Graphics, Pen: LongWord;
begin
  for I := 0 to GetArrayLength(SkinStageMarks) - 1 do begin
    W := SkinStageMarks[I].Width; H := SkinStageMarks[I].Height;
    SkinStageMarks[I].Bitmap.Width := W; SkinStageMarks[I].Bitmap.Height := H;
    SkinClear(SkinStageMarks[I].Bitmap.Canvas.Handle, W, H, SkinCardColor);
    Graphics := SkinGraphics(SkinStageMarks[I].Bitmap.Canvas.Handle);
    try
      if I <= Active then Color := SkinAccent else Color := $606060;
      Pen := SkinPen(Color, ScaleX(1) * 1.5);
      try
        if I = Active then SkinGdiDrawArc(Graphics, Pen, 1.5, 1.5, W - 3, H - 3, -90, 270)
        else SkinGdiEllipse(Graphics, Pen, 1.5, 1.5, W - 3, H - 3);
      finally
        SkinGdiDeletePen(Pen);
      end;
      if I < Active then begin
        SkinLine(Graphics, SkinAccent, ScaleX(1) * 1.5, W * 0.26, H * 0.50, W * 0.43, H * 0.68);
        SkinLine(Graphics, SkinAccent, ScaleX(1) * 1.5, W * 0.43, H * 0.68, W * 0.75, H * 0.33);
      end;
    finally
      SkinGdiDeleteGraphics(Graphics);
    end;
    SkinStageMarks[I].Invalidate;
  end;
end;

procedure SkinState(State: Integer);
var Setup, Progress, Finished: Boolean; I: Integer;
begin
  if not SkinActive then Exit;
  Setup := State = 0; Progress := State = 1; Finished := State = 2;
  WizardForm.OuterNotebook.Visible := False;
  WizardForm.InnerNotebook.Visible := False;
  WizardForm.BackButton.Visible := False;
  if State <> SkinLastState then begin SkinLastState := State; SkinPaintBackground; end;
  SkinHead.Left := ScaleX(330); SkinSubtitle.Left := ScaleX(330);
  SkinHead.Width := ScaleX(610); SkinSubtitle.Width := ScaleX(610);
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
    SkinHead.Width := ScaleX(550); SkinSubtitle.Width := ScaleX(550);
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
  for I := 0 to GetArrayLength(SkinStageMarks) - 1 do SkinStageMarks[I].Visible := Progress;
  if Progress then SkinDrawStages(1);
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
  SkinInitializeGraphics;
  SkinCanvas := TBitmapImage.Create(WizardForm); SkinCanvas.Parent := WizardForm;
  SkinCanvas.Align := alClient; SkinCanvas.Stretch := False; SkinCanvas.SendToBack;
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
  LabelControl.Alignment := taCenter; LabelControl.Font.Style := [fsBold];
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
  SkinStageOne := SkinLabel(WizardForm, '准备安装', 390, 356, 540, 30, 13, SkinAccent, SkinCardColor);
  SkinStageTwo := SkinLabel(WizardForm, '安装文件', 390, 399, 540, 30, 13, SkinWhite, SkinCardColor);
  SkinStageThree := SkinLabel(WizardForm, '完成配置', 390, 442, 540, 30, 13, SkinMuted, SkinCardColor);
  SetArrayLength(SkinStageMarks, 3);
  for I := 0 to 2 do begin
    SkinStageMarks[I] := TBitmapImage.Create(WizardForm); SkinStageMarks[I].Parent := WizardForm;
    SkinStageMarks[I].SetBounds(ScaleX(358), ScaleY(362 + 43 * I), ScaleX(18), ScaleY(18));
  end;
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
  SkinConfigureFrame(WizardForm.Handle);
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
      SkinStageMarks[0].Visible := False; SkinStageMarks[1].Visible := False; SkinStageMarks[2].Visible := False;
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
  SkinShutdownGraphics;
  SkinActive := False;
end;
