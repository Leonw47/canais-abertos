; Instalador do Canais Abertos (NSIS 3, Modern UI 2) — instala só para o usuário, sem pedir administrador.
Unicode true
!include "MUI2.nsh"

!define APP "Canais Abertos"
!define VERSAO "1.1.0"
!define EXE "Canais Abertos.exe"
!define CHAVE "Software\Microsoft\Windows\CurrentVersion\Uninstall\CanaisAbertos"

Name "${APP}"
OutFile "CanaisAbertos-Setup-${VERSAO}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "Software\CanaisAbertos" "Pasta"
RequestExecutionLevel user
SetCompressor /SOLID lzma
BrandingText "${APP} ${VERSAO}"
VIProductVersion "${VERSAO}.0"
VIAddVersionKey "ProductName" "${APP}"
VIAddVersionKey "FileDescription" "Instalador do ${APP} — TV ao vivo em português"
VIAddVersionKey "FileVersion" "${VERSAO}"
VIAddVersionKey "ProductVersion" "${VERSAO}"
VIAddVersionKey "LegalCopyright" "Uso caseiro e não comercial"

!define MUI_ICON "canais_abertos.ico"
!define MUI_UNICON "canais_abertos.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Instalar o ${APP}"
!define MUI_WELCOMEPAGE_TEXT "TV ao vivo em português, só com emissoras e canais gratuitos oficiais (Pluto TV Brasil, TVs públicas, educativas e regionais), incluindo canais infantis.$\r$\n$\r$\nO programa já traz o motor de vídeo: não precisa ter o VLC instalado.$\r$\n$\r$\nClique em Próximo para continuar."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Abrir o ${APP} agora"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "PortugueseBR"

Section "Programa" SecPrograma
  SetOutPath "$INSTDIR"
  ; apaga a versão anterior do pacote (mantém favoritos e configurações, que ficam em %APPDATA%)
  RMDir /r "$INSTDIR\_internal"
  File /r "dist\${APP}\*.*"
  CreateShortcut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${EXE}" "" "$INSTDIR\${EXE}" 0
  WriteUninstaller "$INSTDIR\Desinstalar.exe"
  WriteRegStr HKCU "Software\CanaisAbertos" "Pasta" "$INSTDIR"
  WriteRegStr HKCU "${CHAVE}" "DisplayName" "${APP}"
  WriteRegStr HKCU "${CHAVE}" "DisplayVersion" "${VERSAO}"
  WriteRegStr HKCU "${CHAVE}" "Publisher" "Uso caseiro"
  WriteRegStr HKCU "${CHAVE}" "DisplayIcon" "$INSTDIR\${EXE}"
  WriteRegStr HKCU "${CHAVE}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${CHAVE}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegStr HKCU "${CHAVE}" "QuietUninstallString" '"$INSTDIR\Desinstalar.exe" /S'
  WriteRegDWORD HKCU "${CHAVE}" "NoModify" 1
  WriteRegDWORD HKCU "${CHAVE}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${CHAVE}"
  DeleteRegKey HKCU "Software\CanaisAbertos"
SectionEnd
