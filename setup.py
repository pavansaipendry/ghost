"""
py2app build script for Ghost
Usage: python setup.py py2app
"""

from setuptools import setup

APP = ['ghost/main.py']

DATA_FILES = [
    ('ghost/ui/web', [
        'ghost/ui/web/index.html',
        'ghost/ui/web/style.css',
        'ghost/ui/web/app.js',
    ]),
    ('ghost/config', [
        'ghost/config/settings.toml',
    ]),
]

OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'Ghost',
        'CFBundleDisplayName': 'Ghost',
        'CFBundleIdentifier': 'com.ghost.stealthviewer',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSUIElement': True,  # No dock icon
        'NSHumanReadableCopyright': 'Ghost - Stealth Document Viewer',
    },
    'packages': [
        'AppKit',
        'WebKit',
        'Foundation',
        'objc',
        'fitz',
        'docx',
        'markdown',
        'pygments',
        'pynput',
        'toml',
    ],
    'includes': [
        'ghost',
        'ghost.config',
        'ghost.window',
        'ghost.window.panel',
        'ghost.window.webview',
        'ghost.ui',
        'ghost.ui.tray',
        'ghost.documents',
        'ghost.documents.loader',
        'ghost.documents.pdf_parser',
        'ghost.documents.docx_parser',
        'ghost.documents.md_parser',
        'ghost.documents.txt_parser',
        'ghost.input',
        'ghost.input.keys',
    ],
}

setup(
    name='Ghost',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
