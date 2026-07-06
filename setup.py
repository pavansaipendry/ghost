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
    ('documents', [
        'sample_docs/Set_1_Video_Streaming_Service.md',
        'sample_docs/Set_2_Facebook_NewsFeed.md',
        'sample_docs/Set_3_Uber_Carpool.md',
        'sample_docs/Set_4_DoorDash_Grocery.md',
        'sample_docs/Set_5_Social_Network_Private_Accounts.md',
        'sample_docs/Set_6_Car_Rental_Expansion.md',
        'sample_docs/Set_7_Messaging_App.md',
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
