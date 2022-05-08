from setuptools import setup

setup(
    name='x2gpaero',
    description='Gateway for APRS/OGN/X traffic to glideport.aero',
    version='0.0.3',
    setup_requires=[],
    install_requires=[
        'aprslib',
        'ogn-client',
        'requests',
        'timezonefinder',
        'pytz',
        'datetime',
    ],
    include_package_data=True,
    packages=['x2gpaero'],
    data_files=['LICENSE'],
    entry_points={
        'console_scripts': [
            'aprs2gpaero = x2gpaero.aprs2gp:main',
            'ogn2gpaero = x2gpaero.ogn2gp:main'
        ]
    },
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GNU General Public License version 3',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Topic :: Utilities',
    ],
)
