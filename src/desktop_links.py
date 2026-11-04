"""Replace obsolete Wallaby URL shortcuts with the installed dynamic launcher."""
import os,re,stat,tempfile
from pathlib import Path

LAUNCHER='''[Desktop Entry]
Type=Application
Name=Wallaby Agent
Comment=Configure Wallaby Agent services
Exec=wallaby-agent configure
Icon=wallaby-agent
Terminal=false
Categories=Utility;Network;
'''

def repair():
    home=Path.home();config=Path(os.environ.get('XDG_CONFIG_HOME',home/'.config'))
    desktop=home/'Desktop'
    try:
        match=re.search(r'^XDG_DESKTOP_DIR="([^"\n]+)"$',(config/'user-dirs.dirs').read_text(),re.M)
        if match:
            value=match[1].replace('$HOME',str(home))
            if '$' not in value and Path(value).is_absolute():desktop=Path(value)
    except OSError:pass
    applications=Path(os.environ.get('XDG_DATA_HOME',home/'.local/share'))/'applications'
    for folder in {desktop,applications}:
        for path in folder.glob('*.desktop'):
            temporary=None
            try:
                info=path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():continue
                text=path.read_text()
                if not re.search(r'^Name=Wallaby Agent(?: Configuration)?$',text,re.M):continue
                if not re.search(r'^(?:URL=|Exec=.*https?://)',text,re.M):continue
                fd,temporary=tempfile.mkstemp(prefix='.wallaby-shortcut-',dir=folder)
                with os.fdopen(fd,'w') as output:output.write(LAUNCHER)
                os.chmod(temporary,stat.S_IMODE(info.st_mode));os.replace(temporary,path);temporary=None
            except (OSError,UnicodeError):pass
            finally:
                if temporary is not None:Path(temporary).unlink(missing_ok=True)
