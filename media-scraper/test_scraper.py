#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Quick test for the Media Scraper scrape() function."""

import sys
from server import scrape

def main():
    test_url = sys.argv[1] if len(sys.argv) > 1 else 'https://example.com'
    print(f'Testing scrape on: {test_url}')
    print('-' * 60)
    try:
        result = scrape(test_url)
        print(f'Title: {result["title"]}')
        print(f'Videos ({len(result["videos"])}):')
        for v in result['videos']:
            print(f'  - {v}')
        print(f'Audios ({len(result["audios"])}):')
        for a in result['audios']:
            print(f'  - {a}')
        print(f'Images ({len(result["images"])}):')
        for i in result['images']:
            print(f'  - {i}')
        print('-' * 60)
        print('TEST PASSED')
    except Exception as e:
        print(f'TEST FAILED: {e}')
        sys.exit(1)

if __name__ == '__main__':
    main()