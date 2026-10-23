"""Package the supplied GT Studio artwork into a macOS ICNS without redrawing it."""
from pathlib import Path
import plistlib
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'frameforge/assets/gt-studio.png'
BUNDLE = ROOT/'GT Studio.app/Contents'


def main():
    resource = BUNDLE/'Resources/GTStudio.icns'
    resource.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='gt-studio-icon-') as temporary:
        iconset = Path(temporary)/'GTStudio.iconset'
        iconset.mkdir()
        for points in (16,32,128,256,512):
            for scale in (1,2):
                size = points*scale
                destination = iconset/f'icon_{points}x{points}{"@2x" if scale==2 else ""}.png'
                subprocess.run(['sips','-z',str(size),str(size),str(SOURCE),'--out',str(destination)],check=True,capture_output=True)
        subprocess.run(['iconutil','--convert','icns',str(iconset),'--output',str(resource)],check=True)
    plist = BUNDLE/'Info.plist'
    info = plistlib.loads(plist.read_bytes())
    info['CFBundleIconFile'] = resource.name
    plist.write_bytes(plistlib.dumps(info,sort_keys=False))
    print(resource)


if __name__ == '__main__':
    main()
