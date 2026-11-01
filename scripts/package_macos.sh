#!/bin/bash
# 在 macOS 上打出「鑫垚设计PDF编辑器.app」，并做成 dmg。
# 产物文件名用 ASCII，方便放进 GitHub Release；应用本身的名字是中文。
set -euo pipefail

cd "$(dirname "$0")/.."

APP_NAME="鑫垚设计PDF编辑器"
ARCH="$(uname -m)"
ICON_DIR="$(mktemp -d)"
STAGE="$(mktemp -d)"
cleanup() {
  rm -rf "$ICON_DIR" "$STAGE"
}
trap cleanup EXIT

mkdir -p "$ICON_DIR/AppIcon.iconset"
sips -z 16 16 assets/app.png --out "$ICON_DIR/AppIcon.iconset/icon_16x16.png" >/dev/null
sips -z 32 32 assets/app.png --out "$ICON_DIR/AppIcon.iconset/icon_16x16@2x.png" >/dev/null
sips -z 32 32 assets/app.png --out "$ICON_DIR/AppIcon.iconset/icon_32x32.png" >/dev/null
sips -z 64 64 assets/app.png --out "$ICON_DIR/AppIcon.iconset/icon_32x32@2x.png" >/dev/null
sips -z 128 128 assets/app.png --out "$ICON_DIR/AppIcon.iconset/icon_128x128.png" >/dev/null
sips -z 256 256 assets/app.png --out "$ICON_DIR/AppIcon.iconset/icon_128x128@2x.png" >/dev/null
sips -z 256 256 assets/app.png --out "$ICON_DIR/AppIcon.iconset/icon_256x256.png" >/dev/null
sips -z 512 512 assets/app.png --out "$ICON_DIR/AppIcon.iconset/icon_256x256@2x.png" >/dev/null
sips -z 512 512 assets/app.png --out "$ICON_DIR/AppIcon.iconset/icon_512x512.png" >/dev/null
sips -z 1024 1024 assets/app.png --out "$ICON_DIR/AppIcon.iconset/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$ICON_DIR/AppIcon.iconset" -o "$ICON_DIR/AppIcon.icns"

python -m PyInstaller --noconfirm --clean --windowed --onedir \
  --name "$APP_NAME" \
  --icon "$ICON_DIR/AppIcon.icns" \
  --osx-bundle-identifier com.xinyao.pdfeditor \
  --collect-all pymupdf \
  --collect-all PySide6 \
  --collect-all PIL \
  main.py

APP="dist/${APP_NAME}.app"
PLIST="${APP}/Contents/Info.plist"
if [[ ! -d "$APP" ]]; then
  echo "没有生成 ${APP}" >&2
  exit 1
fi

plist_set() {
  local key="$1"
  local value="$2"
  if /usr/libexec/PlistBuddy -c "Set :${key} ${value}" "$PLIST" 2>/dev/null; then
    return
  fi
  /usr/libexec/PlistBuddy -c "Add :${key} string ${value}" "$PLIST"
}

plist_set CFBundleDisplayName "$APP_NAME"
plist_set CFBundleName "$APP_NAME"
plist_set CFBundleDevelopmentRegion "zh-Hans"
/usr/libexec/PlistBuddy -c "Add :CFBundleLocalizations array" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleLocalizations:0 string zh-Hans" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :CFBundleLocalizations:0 zh-Hans" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :NSHighResolutionCapable true" "$PLIST" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$PLIST"

mkdir -p "${APP}/Contents/Resources/zh-Hans.lproj"
cat > "${APP}/Contents/Resources/zh-Hans.lproj/InfoPlist.strings" <<'EOF'
CFBundleDisplayName = "鑫垚设计PDF编辑器";
CFBundleName = "鑫垚设计PDF编辑器";
EOF

# 临时签名，方便在打包机上做自检。下载后仍会被 Gatekeeper 拦截，需要用户手动打开。
codesign --force --deep --sign - "$APP"

BIN="${APP}/Contents/MacOS/${APP_NAME}"
if [[ ! -x "$BIN" ]]; then
  echo "找不到可执行文件，Contents/MacOS 里有：" >&2
  ls -la "${APP}/Contents/MacOS" >&2
  exit 1
fi
QT_QPA_PLATFORM=offscreen "$BIN" --self-check

cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp scripts/macos-first-open.txt "$STAGE/请先阅读.txt"

DMG="dist/XinyaoPDFEditor-macos-${ARCH}.dmg"
rm -f "$DMG"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "已生成 ${DMG}"
