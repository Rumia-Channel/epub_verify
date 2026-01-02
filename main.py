import argparse
import sys
import zipfile
import logging
import posixpath
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Set
from urllib.parse import unquote
from bs4 import BeautifulSoup

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

class EpubValidator:
    """Class responsible for validating a single EPUB file."""
    
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.missing_resources: List[str] = []
        self.is_valid_zip = True

    def validate(self) -> bool:
        """
        Validates the EPUB file.
        Returns True if the file is valid (all referenced images exist), False otherwise.
        """
        if not zipfile.is_zipfile(self.file_path):
            self.is_valid_zip = False
            return False

        try:
            with zipfile.ZipFile(self.file_path, 'r') as zf:
                all_files = set(zf.namelist())
                self._check_content_files(zf, all_files)
        except zipfile.BadZipFile:
            self.is_valid_zip = False
            return False
        except Exception as e:
            logger.error(f"Error processing {self.file_path.name}: {e}")
            return False

        return len(self.missing_resources) == 0

    def _check_content_files(self, zf: zipfile.ZipFile, all_files: Set[str]):
        """Iterates through HTML/XHTML files in the archive and checks image references."""
        for filename in all_files:
            if filename.lower().endswith(('.html', '.xhtml', '.htm')):
                self._scan_file_for_images(zf, filename, all_files)

    def _scan_file_for_images(self, zf: zipfile.ZipFile, html_filename: str, all_files: Set[str]):
        """Parses an HTML file and verifies that referenced images exist."""
        try:
            with zf.open(html_filename) as f:
                # Use lxml for speed and XML support
                soup = BeautifulSoup(f, 'lxml')

            base_dir = posixpath.dirname(html_filename)

            # Check standard <img> tags
            for img in soup.find_all('img'):
                src = img.get('src')
                if src:
                    self._verify_resource(src, base_dir, all_files, html_filename)

            # Check <image> tags (often used in SVGs or EPUB covers)
            for image in soup.find_all('image'):
                # Handle xlink:href and href
                href = image.get('xlink:href') or image.get('href')
                if href:
                    self._verify_resource(href, base_dir, all_files, html_filename)
            
            # Check <link> tags (e.g. for cover images sometimes, though less critical for "missing image" definition)
            # focusing on content images as per requirement.

        except Exception as e:
            logger.debug(f"Could not parse {html_filename} in {self.file_path.name}: {e}")

    def _verify_resource(self, src: str, base_dir: str, all_files: Set[str], context_file: str):
        """Checks if a referenced resource exists in the archive."""
        if src.startswith(('http:', 'https:', 'data:', 'mailto:')):
            return

        # Decode URL (e.g., %20 to space)
        src = unquote(src)

        # Resolve path relative to the HTML file
        target_path = posixpath.normpath(posixpath.join(base_dir, src))

        if target_path not in all_files:
            self.missing_resources.append(f"Missing: '{target_path}' (referenced in '{context_file}')")


class EpubSorter:
    """Class responsible for processing a directory of EPUB files."""

    def __init__(self, directory: Path, isolate_broken: bool = False):
        self.directory = directory
        self.isolate_broken = isolate_broken
        self.valid_epubs: List[Path] = []
        self.broken_epubs: List[Path] = []

    def process(self):
        """Scans the directory and validates all EPUB files."""
        if not self.directory.exists():
            logger.error(f"Directory not found: {self.directory}")
            return

        files = list(self.directory.glob("*.epub"))
        if not files:
            logger.info("No EPUB files found in the specified directory.")
            return

        logger.info(f"Found {len(files)} EPUB files. Starting validation...\n")

        for file_path in files:
            validator = EpubValidator(file_path)
            is_valid = validator.validate()

            if is_valid:
                self.valid_epubs.append(file_path)
            else:
                self.broken_epubs.append(file_path)
                logger.info(f"[BROKEN] {file_path.name}")
                if not validator.is_valid_zip:
                     logger.info("  - Invalid ZIP file")
                for error in validator.missing_resources:
                    logger.info(f"  - {error}")
                logger.info("") # Empty line for readability

        if self.isolate_broken and self.broken_epubs:
            self._isolate_broken_files()

        self._print_summary()

    def _isolate_broken_files(self):
        """Moves broken files to an isolation directory."""
        isolation_dir = self.directory / "broken"
        try:
            isolation_dir.mkdir(exist_ok=True)
            logger.info(f"Moving broken files to: {isolation_dir}")
            
            for file_path in self.broken_epubs:
                destination = isolation_dir / file_path.name
                # Avoid overwriting if file already exists in destination
                if destination.exists():
                    logger.warning(f"File already exists in isolation folder, skipping: {file_path.name}")
                    continue
                
                try:
                    shutil.move(str(file_path), str(destination))
                    logger.info(f"Moved: {file_path.name}")
                except Exception as e:
                    logger.error(f"Failed to move {file_path.name}: {e}")

            logger.info("") # Spacing
        except Exception as e:
            logger.error(f"Failed to create isolation directory: {e}")

    def _print_summary(self):
        """Prints the final summary of the validation process."""
        print("-" * 30)
        print("Validation Summary")
        print("-" * 30)
        print(f"Total Files Checked: {len(self.valid_epubs) + len(self.broken_epubs)}")
        print(f"Valid Files:         {len(self.valid_epubs)}")
        print(f"Broken Files:        {len(self.broken_epubs)}")
        if self.isolate_broken and self.broken_epubs:
             print(f"Moved to:            {self.directory / 'broken'}")
        print("-" * 30)


def main():
    parser = argparse.ArgumentParser(description="Scan EPUB files for missing image references.")
    parser.add_argument("directory", type=Path, help="Directory containing EPUB files to check")
    parser.add_argument("--isolate", action="store_true", help="Move broken EPUB files to a 'broken' subdirectory")
    
    args = parser.parse_args()
    
    sorter = EpubSorter(args.directory, isolate_broken=args.isolate)
    sorter.process()


if __name__ == "__main__":
    main()
