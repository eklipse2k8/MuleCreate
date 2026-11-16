; Inno Setup: installer from dist/Mule (build packaging/mule.spec first). Build: ISCC.exe packaging\mule.iss
; Result: dist\Mule_Setup.exe. Without a code signature Windows SmartScreen warns ("Run anyway").
#define AppVersion "0.99-alpha"

[Setup]
AppId={{6E0B1E55-3C7F-4B1E-9A52-4D1F6E8A7C11}
AppName=Mule
AppVersion={#AppVersion}
AppPublisher=Felix Barthel
DefaultDirName={autopf}\Mule
DefaultGroupName=Mule
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Mule_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Mule.exe
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "association"; Description: "Open .mule scenes with Mule"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Mule\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Mule"; Filename: "{app}\Mule.exe"
Name: "{group}\{cm:UninstallProgram,Mule}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Mule"; Filename: "{app}\Mule.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\.mule"; ValueType: string; ValueData: "Mule.Scene"; Flags: uninsdeletevalue; Tasks: association
Root: HKA; Subkey: "Software\Classes\.json\OpenWithProgids"; ValueType: string; ValueName: "Mule.Scene"; ValueData: ""; Flags: uninsdeletevalue; Tasks: association
Root: HKA; Subkey: "Software\Classes\Mule.Scene\DefaultIcon"; ValueType: string; ValueData: """{app}\Mule.exe"",0"; Tasks: association
Root: HKA; Subkey: "Software\Classes\Mule.Scene"; ValueType: string; ValueData: "Mule scene"; Flags: uninsdeletekey; Tasks: association
Root: HKA; Subkey: "Software\Classes\Mule.Scene\shell\open\command"; ValueType: string; ValueData: """{app}\Mule.exe"" ""%1"""; Tasks: association

[Run]
Filename: "{app}\Mule.exe"; Description: "{cm:LaunchProgram,Mule}"; Flags: nowait postinstall skipifsilent
