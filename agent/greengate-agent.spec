# PyInstaller spec for GreenGate-Agent.exe (Windows). Build on Windows:
#   pip install -r agent/requirements.txt pyinstaller==6.11.1
#   pyinstaller --noconfirm --clean agent/greengate-agent.spec
# Result: dist/GreenGate-Agent.exe (one file, console kept so "greengate_agent pair" can show the code).
# -*- mode: python ; coding: utf-8 -*-
import os
a = Analysis([os.path.join(SPECPATH, 'greengate_agent.py')], pathex=[], binaries=[], datas=[],
             hiddenimports=['nacl.bindings', 'nacl.public', 'mss.windows', 'PIL.Image', 'PIL.JpegImagePlugin'],
             hookspath=[], runtime_hooks=[], excludes=['tkinter'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='GreenGate-Agent', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True, disable_windowed_traceback=False)
