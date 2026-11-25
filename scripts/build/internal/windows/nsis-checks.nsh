!macro NSIS_HOOK_PREINSTALL
  ReadRegStr $0 HKCU "${MANUPRODUCTKEY}" "InstallDir"
  ${If} $0 != ""
    Abort "Uninstall the Loushang MSI installation before installing this setup."
  ${EndIf}
  ${If} ${FileExists} "$INSTDIR\${MAINBINARYNAME}.exe"
  ${AndIfNot} ${FileExists} "$INSTDIR\uninstall.exe"
    Abort "The selected folder contains a different Loushang installation."
  ${EndIf}
!macroend
