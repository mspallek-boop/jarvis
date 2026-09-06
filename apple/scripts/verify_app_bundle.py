#!/usr/bin/env python3
"""Validate signed device artifacts before installation; never read app secrets."""
import argparse
import plistlib
import subprocess
from pathlib import Path


def run(*args):
    return subprocess.run(args, check=True, capture_output=True).stdout


def info(app):
    path = app / 'Contents/Info.plist' if (app / 'Contents').exists() else app / 'Info.plist'
    return plistlib.loads(path.read_bytes())


def verify_signature(app):
    run('codesign', '--verify', '--deep', '--strict', str(app))
    signature = subprocess.run(['codesign', '-dv', '--verbose=2', str(app)],
                               check=True, capture_output=True).stderr.decode()
    assert 'Signature=adhoc' not in signature, 'A stable development signature is required'
    assert 'TeamIdentifier=V86U93FGU3' in signature, 'Unexpected signing team'


def verify_mac(app):
    verify_signature(app)
    metadata = info(app)
    assert metadata['CFBundleIdentifier'] == 'at.marlon.jarvis.macos'
    assert metadata['NSMicrophoneUsageDescription']
    assert metadata['NSSpeechRecognitionUsageDescription']
    entitlements = plistlib.loads(run('codesign', '-d', '--entitlements', ':-', str(app)))
    assert entitlements.get('com.apple.security.device.audio-input') is True, 'Missing microphone entitlement'
    print('PASS: signed macOS app, stable identity, microphone entitlement, privacy descriptions')


def verify_ios(app):
    verify_signature(app)
    metadata = info(app)
    assert metadata['CFBundleIdentifier'] == 'at.marlon.jarvis.ios'
    watch = app / 'Watch/JARVIS-Watch.app'
    assert watch.is_dir(), 'Companion app missing from Watch/ embedding directory'
    verify_signature(watch)
    companion = info(watch)
    assert companion['CFBundleIdentifier'] == 'at.marlon.jarvis.ios.watchkitapp'
    assert companion['WKCompanionAppBundleIdentifier'] == metadata['CFBundleIdentifier']
    assert companion['WKApplication'] is True
    assert companion['CFBundleVersion'] == metadata['CFBundleVersion']
    assert companion['CFBundleShortVersionString'] == metadata['CFBundleShortVersionString']
    assert 'WatchOS' in companion['CFBundleSupportedPlatforms']
    assert (watch / companion['CFBundleExecutable']).is_file()
    print('PASS: signed iOS app, embedded executable watchOS companion, matching versions and bundle IDs')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mac', type=Path)
    parser.add_argument('--ios', type=Path)
    args = parser.parse_args()
    if not args.mac and not args.ios:
        parser.error('Pass --mac and/or --ios with a built app bundle')
    if args.mac:
        verify_mac(args.mac)
    if args.ios:
        verify_ios(args.ios)
