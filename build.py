import os
import PyInstaller.__main__

options = [
    'main.py',
    '--name=MediaSegmenter',
    '--windowed',
    '--onefile',
    '--clean',
    '--collect-all', 'customtkinter'
]

PyInstaller.__main__.run(options)
