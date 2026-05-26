import os
import PyInstaller.__main__

options = [
    'main.py',
    '--name=MediaSegmenter',
    '--windowed',
    '--onefile',
    '--clean'
]

PyInstaller.__main__.run(options)
