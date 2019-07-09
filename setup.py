# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

PACKAGE_NAME = 'hxtool'
PACKAGE_VERSION = '0.3.0a4'

INSTALL_REQUIRES = [
    'coloredlogs',
    'gpxpy',
    'ipython',
    'pyserial'
]

TESTS_REQUIRE = [
    'coverage',
    'pycodestyle',
    'pytest',
    'pytest-pycodestyle',
    'pytest-runner'
]

DEV_REQUIRES = TESTS_REQUIRE

setup(
    name=PACKAGE_NAME,
    version=PACKAGE_VERSION,
    description='Tool for Yaesu / Stadard Horizon HX series radio flashing and configuration',
    classifiers=[
        'Environment :: Console',
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Intended Audience :: Customer Service',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Natural Language :: English',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: POSIX :: Linux',
        'Operating System :: Microsoft :: Windows :: Windows 10',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Communications :: Ham Radio'
    ],
    keywords=['hamradio', 'radio', 'maritime', 'yaesu', 'standard horizon', 'hx870', 'hx870e',
              'hx890', 'hx890e', 'firmware', 'flashing', 'mmsi', 'atis'],
    author='Christiane Ruetten',
    author_email='cr@23bit.net',
    url='https://github.com/cr/pyhx870',
    download_url='https://github.com/cr/pyhx870/archive/master.tar.gz',
    license='GPLv3',
    packages=find_packages(exclude=["tests"]),
    include_package_data=True,  # See MANIFEST.in
    zip_safe=True,
    use_2to3=False,
    install_requires=INSTALL_REQUIRES,
    tests_require=TESTS_REQUIRE,
    extras_require={'dev': DEV_REQUIRES},  # For `pip install -e .[dev]`
    entry_points={
        'console_scripts': [
            'hxtool = hxtool.main:main'
        ]
    }
)
