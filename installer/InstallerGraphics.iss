// OS graphics only: GDI+ for smooth controls, DWM for the actual window frame.
type
  TSkinGdiStartup = record
    Version, DebugCallback, SuppressThread, SuppressCodecs: LongWord;
  end;
  TSkinMargins = record Left, Right, Top, Bottom: Integer; end;
  TSkinPaintInfo = record
    DC: LongWord;
    Erase: LongInt;
    Left, Top, Right, Bottom, Restore, IncUpdate: LongInt;
    Reserved0, Reserved1, Reserved2, Reserved3: LongInt;
    Reserved4, Reserved5, Reserved6, Reserved7: LongInt;
  end;

function SkinGdiStartup(var Token: LongWord; var Input: TSkinGdiStartup; Output: LongWord): Integer;
  external 'GdiplusStartup@gdiplus.dll stdcall';
procedure SkinGdiShutdown(Token: LongWord); external 'GdiplusShutdown@gdiplus.dll stdcall';
function SkinGdiGraphics(DC: LongWord; var Graphics: LongWord): Integer;
  external 'GdipCreateFromHDC@gdiplus.dll stdcall';
function SkinGdiDeleteGraphics(Graphics: LongWord): Integer;
  external 'GdipDeleteGraphics@gdiplus.dll stdcall';
function SkinGdiSmoothing(Graphics: LongWord; Mode: Integer): Integer;
  external 'GdipSetSmoothingMode@gdiplus.dll stdcall';
function SkinGdiPixelOffset(Graphics: LongWord; Mode: Integer): Integer;
  external 'GdipSetPixelOffsetMode@gdiplus.dll stdcall';
function SkinGdiInterpolation(Graphics: LongWord; Mode: Integer): Integer;
  external 'GdipSetInterpolationMode@gdiplus.dll stdcall';
function SkinGdiBrush(Color: LongWord; var Brush: LongWord): Integer;
  external 'GdipCreateSolidFill@gdiplus.dll stdcall';
function SkinGdiDeleteBrush(Brush: LongWord): Integer;
  external 'GdipDeleteBrush@gdiplus.dll stdcall';
function SkinGdiPen(Color: LongWord; Width: Single; Units: Integer; var Pen: LongWord): Integer;
  external 'GdipCreatePen1@gdiplus.dll stdcall';
function SkinGdiDeletePen(Pen: LongWord): Integer; external 'GdipDeletePen@gdiplus.dll stdcall';
function SkinGdiStartCap(Pen: LongWord; Cap: Integer): Integer;
  external 'GdipSetPenStartCap@gdiplus.dll stdcall';
function SkinGdiEndCap(Pen: LongWord; Cap: Integer): Integer;
  external 'GdipSetPenEndCap@gdiplus.dll stdcall';
function SkinGdiPath(Mode: Integer; var Path: LongWord): Integer;
  external 'GdipCreatePath@gdiplus.dll stdcall';
function SkinGdiDeletePath(Path: LongWord): Integer; external 'GdipDeletePath@gdiplus.dll stdcall';
function SkinGdiArc(Path: LongWord; X, Y, W, H, Start, Sweep: Single): Integer;
  external 'GdipAddPathArc@gdiplus.dll stdcall';
function SkinGdiClosePath(Path: LongWord): Integer;
  external 'GdipClosePathFigure@gdiplus.dll stdcall';
function SkinGdiFillPath(Graphics, Brush, Path: LongWord): Integer;
  external 'GdipFillPath@gdiplus.dll stdcall';
function SkinGdiDrawPath(Graphics, Pen, Path: LongWord): Integer;
  external 'GdipDrawPath@gdiplus.dll stdcall';
function SkinGdiLine(Graphics, Pen: LongWord; X1, Y1, X2, Y2: Single): Integer;
  external 'GdipDrawLine@gdiplus.dll stdcall';
function SkinGdiEllipse(Graphics, Pen: LongWord; X, Y, W, H: Single): Integer;
  external 'GdipDrawEllipse@gdiplus.dll stdcall';
function SkinGdiDrawArc(Graphics, Pen: LongWord; X, Y, W, H, Start, Sweep: Single): Integer;
  external 'GdipDrawArc@gdiplus.dll stdcall';
function SkinGdiLoadImage(FileName: String; var Image: LongWord): Integer;
  external 'GdipLoadImageFromFile@gdiplus.dll stdcall';
function SkinGdiDisposeImage(Image: LongWord): Integer;
  external 'GdipDisposeImage@gdiplus.dll stdcall';
function SkinGdiDrawImage(Graphics, Image: LongWord; X, Y, W, H: Integer): Integer;
  external 'GdipDrawImageRectI@gdiplus.dll stdcall';
function SkinSolidBrush(Color: Integer): LongWord;
  external 'CreateSolidBrush@gdi32.dll stdcall';
function SkinGdiFillRect(DC: LongWord; var R: TSkinRect; Brush: LongWord): Integer;
  external 'FillRect@user32.dll stdcall';
function SkinDeleteGdiObject(Obj: LongWord): Boolean;
  external 'DeleteObject@gdi32.dll stdcall';
function SkinBeginPaint(Wnd: HWND; var Info: TSkinPaintInfo): LongWord;
  external 'BeginPaint@user32.dll stdcall';
function SkinEndPaint(Wnd: HWND; var Info: TSkinPaintInfo): Boolean;
  external 'EndPaint@user32.dll stdcall';
function SkinGetWindowLong(Wnd: HWND; Index: Integer): LongInt;
  external 'GetWindowLongW@user32.dll stdcall';
function SkinSetWindowLong(Wnd: HWND; Index, Value: LongInt): LongInt;
  external 'SetWindowLongW@user32.dll stdcall';
function SkinSetWindowPos(Wnd, After: HWND; X, Y, W, H: Integer; Flags: LongWord): Boolean;
  external 'SetWindowPos@user32.dll stdcall';
function SkinWindowTheme(Wnd: HWND; App, Ids: String): Integer;
  external 'SetWindowTheme@uxtheme.dll stdcall';
function SkinDwmAttribute(Wnd: HWND; Attribute: Integer; var Value: Integer; Size: Integer): Integer;
  external 'DwmSetWindowAttribute@dwmapi.dll stdcall';
function SkinDwmExtend(Wnd: HWND; var Margins: TSkinMargins): Integer;
  external 'DwmExtendFrameIntoClientArea@dwmapi.dll stdcall';

var
  SkinGraphicsToken: LongWord;
  SkinNativeFrameReady: Boolean;
  SkinBackgroundImages: array[0..2] of LongWord;

procedure SkinCheckGraphics(Status: Integer; Operation: String);
begin
  if Status <> 0 then RaiseException('Installer graphics ' + Operation + ' failed: ' + IntToStr(Status));
end;

function SkinArgb(Color: Integer): LongWord;
begin
  Result := $FF000000 or ((Color and $FF) shl 16) or (Color and $FF00) or ((Color shr 16) and $FF);
end;

procedure SkinClear(DC: LongWord; W, H, Color: Integer);
var R: TSkinRect; Brush: LongWord;
begin
  R.Left := 0; R.Top := 0; R.Right := W; R.Bottom := H;
  Brush := SkinSolidBrush(Color);
  try
    { FillRect covers every pixel. A null-pen GDI Rectangle leaves edge pixels. }
    SkinGdiFillRect(DC, R, Brush);
  finally
    SkinDeleteGdiObject(Brush);
  end;
end;

function SkinGraphics(DC: LongWord): LongWord;
begin
  if SkinGdiGraphics(DC, Result) <> 0 then RaiseException('Cannot create installer drawing surface');
  SkinGdiSmoothing(Result, 4); { AntiAlias }
  SkinGdiPixelOffset(Result, 4); { Half-pixel sampling }
  SkinGdiInterpolation(Result, 7); { HighQualityBicubic }
end;

function SkinPen(Color: Integer; Width: Single): LongWord;
begin
  if SkinGdiPen(SkinArgb(Color), Width, 2, Result) <> 0 then RaiseException('Cannot create installer pen');
  SkinGdiStartCap(Result, 2); SkinGdiEndCap(Result, 2);
end;

procedure SkinRounded(Graphics: LongWord; X, Y, W, H, Radius: Single; Fill, Edge: Integer; Stroke: Single);
var Path, Brush, Pen: LongWord; D: Single;
begin
  D := Radius * 2;
  if D > W then D := W;
  if D > H then D := H;
  SkinCheckGraphics(SkinGdiPath(0, Path), 'path');
  try
    SkinCheckGraphics(SkinGdiArc(Path, X, Y, D, D, 180, 90), 'rounded geometry');
    SkinCheckGraphics(SkinGdiArc(Path, X + W - D, Y, D, D, 270, 90), 'rounded geometry');
    SkinCheckGraphics(SkinGdiArc(Path, X + W - D, Y + H - D, D, D, 0, 90), 'rounded geometry');
    SkinCheckGraphics(SkinGdiArc(Path, X, Y + H - D, D, D, 90, 90), 'rounded geometry');
    SkinCheckGraphics(SkinGdiClosePath(Path), 'rounded geometry');
    SkinCheckGraphics(SkinGdiBrush(SkinArgb(Fill), Brush), 'rounded geometry');
    try SkinCheckGraphics(SkinGdiFillPath(Graphics, Brush, Path), 'fill'); finally SkinGdiDeleteBrush(Brush); end;
    if Stroke > 0 then begin
      Pen := SkinPen(Edge, Stroke);
      try SkinCheckGraphics(SkinGdiDrawPath(Graphics, Pen, Path), 'stroke'); finally SkinGdiDeletePen(Pen); end;
    end;
  finally
    SkinGdiDeletePath(Path);
  end;
end;

procedure SkinLine(Graphics: LongWord; Color: Integer; Width, X1, Y1, X2, Y2: Single);
var Pen: LongWord;
begin
  Pen := SkinPen(Color, Width);
  try SkinCheckGraphics(SkinGdiLine(Graphics, Pen, X1, Y1, X2, Y2), 'line'); finally SkinGdiDeletePen(Pen); end;
end;

procedure SkinConfigureFrame(Wnd: HWND);
var Value: Integer; Margins: TSkinMargins;
begin
  SkinNativeFrameReady := True;
  { Keep the DWM frame/shadow while WM_NCCALCSIZE gives us the entire client area. }
  SkinSetWindowLong(Wnd, -16, SkinGetWindowLong(Wnd, -16) or $00C40000);
  Value := 2; { DWMWCP_ROUND; Windows 10 keeps its native square corners. }
  SkinDwmAttribute(Wnd, 33, Value, 4);
  Value := $326A61; { Dim accent frame, COLORREF }
  SkinDwmAttribute(Wnd, 34, Value, 4);
  Margins.Left := 1; Margins.Right := 1; Margins.Top := 1; Margins.Bottom := 1;
  SkinDwmExtend(Wnd, Margins);
  SkinSetWindowPos(Wnd, 0, 0, 0, 0, 0, $0037);
end;

procedure SkinInitializeGraphics;
var Input: TSkinGdiStartup; I: Integer; Name: String;
begin
  Input.Version := 1; Input.DebugCallback := 0; Input.SuppressThread := 0; Input.SuppressCodecs := 0;
  if SkinGdiStartup(SkinGraphicsToken, Input, 0) <> 0 then RaiseException('Cannot initialize installer graphics');
  for I := 0 to 2 do begin
    if I = 0 then Name := 'setup' else if I = 1 then Name := 'progress' else Name := 'finished';
    if SkinGdiLoadImage(ExpandConstant('{tmp}\installer-' + Name + '.bmp'), SkinBackgroundImages[I]) <> 0 then
      RaiseException('Cannot load installer artwork');
  end;
end;

procedure SkinShutdownGraphics;
var I: Integer;
begin
  for I := 0 to 2 do
    if SkinBackgroundImages[I] <> 0 then SkinGdiDisposeImage(SkinBackgroundImages[I]);
  if SkinGraphicsToken <> 0 then SkinGdiShutdown(SkinGraphicsToken);
end;
