"""Build the Vision Card hook from source, outside the installed game."""
from pathlib import Path
import os
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    cmake = os.environ.get('FFR_CMAKE') or shutil.which('cmake')
    if not cmake:
        fallback = Path('C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe')
        if fallback.is_file():
            cmake = str(fallback)
    if not cmake:
        raise RuntimeError('Install CMake with Visual Studio C++ tools, or set FFR_CMAKE')
    if not (ROOT / 'build/abilities/native-bridge-sdk/UE4SS.lib').is_file():
        raise RuntimeError('Build src/ffr-availability-native first to prepare the UE4SS import library')
    output = ROOT / 'build/vision-cards/native'
    subprocess.run([cmake, '-S', str(HERE), '-B', str(output), '-G',
                    'Visual Studio 17 2022', '-A', 'x64'], check=True)
    subprocess.run([cmake, '--build', str(output), '--config', 'Release', '--parallel', '4'], check=True)
    print(output / 'Release/main.dll')


if __name__ == '__main__':
    main()
