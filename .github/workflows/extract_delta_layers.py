#!/usr/bin/env python3
"""Docker Layer Delta Extractor.

Copyright (C) 2025 shawly <shawlyde@gmail.com>

SPDX-License-Identifier: GPL-3.0-or-later

This script extracts only the layer blobs that are not part of a base image 
(delta layers) from an already built Docker image. It identifies which layers 
belong to the base image vs. which layers were added in the built image.

The extracted layer blobs are saved with an index prefix (01_, 02_, etc.) to 
preserve their original order for later extraction.

Usage:
    python3 extract_delta_layers.py BASE_IMAGE BUILT_IMAGE [OPTIONS]

Arguments:
    BASE_IMAGE          Base image tag (e.g., ubuntu:20.04)
    BUILT_IMAGE         Built image tag to extract delta from

Options:
    --output-dir PATH   Output directory for extracted layers (default: ./delta_layers)
    --human            Generate human-readable summary report
    --verbose          Enable verbose logging
"""

import argparse
import docker
import json
import logging
import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple


class DockerLayerExtractor:
    def __init__(self, base_image: str, built_image: str, output_dir: str, verbose: bool = False, human_summary: bool = False):
        self.base_image = base_image
        self.built_image = built_image
        self.output_dir = Path(output_dir)
        self.verbose = verbose
        self.human_summary = human_summary
        
        # Setup logging
        log_level = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Initialize Docker client
        try:
            self.docker_client = docker.from_env()
            self.logger.info("Connected to Docker daemon")
        except Exception as e:
            self.logger.error(f"Failed to connect to Docker: {e}")
            sys.exit(1)
            
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def pull_base_image(self) -> None:
        """Pull the base image to ensure we have the latest version for comparison."""
        self.logger.info(f"Pulling base image: {self.base_image}")
        try:
            self.docker_client.images.pull(self.base_image)
            self.logger.info(f"Successfully pulled {self.base_image}")
        except Exception as e:
            self.logger.error(f"Failed to pull base image {self.base_image}: {e}")
            self.logger.warning("Continuing with locally available base image if present")
        
    def get_image_layers(self, image_identifier: str) -> List[str]:
        """Get the list of layer IDs for an image."""
        try:
            image = self.docker_client.images.get(image_identifier)
            
            # Get the RootFS layers from image inspection
            inspect_data = self.docker_client.api.inspect_image(image.id)
            layers = inspect_data.get('RootFS', {}).get('Layers', [])
            
            self.logger.debug(f"Image {image_identifier} has {len(layers)} layers")
            return layers
            
        except Exception as e:
            self.logger.error(f"Failed to get layers for image {image_identifier}: {e}")
            return []
    
    def get_image_history(self, image_identifier: str) -> List[Dict]:
        """Get the history of an image showing layer information."""
        try:
            image = self.docker_client.images.get(image_identifier)
            history = self.docker_client.api.history(image.id)
            
            self.logger.debug(f"Image {image_identifier} history has {len(history)} entries")
            return history
            
        except Exception as e:
            self.logger.error(f"Failed to get history for image {image_identifier}: {e}")
            return []
    
    def identify_delta_layers(self) -> Tuple[List[str], List[Dict]]:
        """Identify which layers are new (delta) compared to the base image."""
        self.logger.info("Identifying delta layers...")
        
        # Get layers and history for both images
        base_layers = self.get_image_layers(self.base_image)
        built_layers = self.get_image_layers(self.built_image)
        built_history = self.get_image_history(self.built_image)
        
        self.logger.info(f"Base image has {len(base_layers)} layers")
        self.logger.info(f"Built image has {len(built_layers)} layers")
        
        # Simple logic: remove base layers from built layers to get delta layers
        base_layers_set = set(base_layers)
        delta_layers = [layer for layer in built_layers if layer not in base_layers_set]
        
        # Get corresponding history entries for delta layers
        # History is in reverse chronological order (newest first)
        delta_history = built_history[:len(delta_layers)]
        
        self.logger.info(f"Found {len(delta_layers)} delta layers")
        
        if self.verbose:
            self.logger.debug("Base layers:")
            for i, layer in enumerate(base_layers):
                self.logger.debug(f"  Base layer {i+1}: {layer[:12]}...")
            
            self.logger.debug("Built layers:")
            for i, layer in enumerate(built_layers):
                is_delta = layer not in base_layers_set
                self.logger.debug(f"  Built layer {i+1}: {layer[:12]}... {'(DELTA)' if is_delta else '(FROM BASE)'}")
            
            self.logger.debug("Delta layers found:")
            for i, layer in enumerate(delta_layers):
                self.logger.debug(f"  Delta layer {i+1}: {layer[:12]}...")
                if i < len(delta_history):
                    created_by = delta_history[i].get('CreatedBy', 'Unknown')
                    size = delta_history[i].get('Size', 0)
                    self.logger.debug(f"    Created by: {created_by}")
                    self.logger.debug(f"    Size: {size} bytes")
        
        return delta_layers, delta_history
    
    def save_image_as_tar(self) -> str:
        """Save the built image as a tar file for layer extraction."""
        tar_path = self.output_dir / f"{self.built_image.replace(':', '_').replace('/', '_')}.tar"
        
        self.logger.info(f"Saving image to tar file: {tar_path}")
        
        try:
            image = self.docker_client.images.get(self.built_image)
            
            # Save image to tar
            with open(tar_path, 'wb') as f:
                for chunk in image.save():
                    f.write(chunk)
            
            self.logger.info(f"Image saved to: {tar_path}")
            return str(tar_path)
            
        except Exception as e:
            self.logger.error(f"Failed to save image as tar: {e}")
            return None
    
    def extract_layers_from_tar(self, tar_path: str, delta_layers: List[str]) -> List[str]:
        """Extract delta layers from the saved tar file."""
        self.logger.info("Extracting delta layers from tar file...")
        
        extracted_layers = []
        
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # Extract the tar file
                subprocess.run(['tar', '-xf', tar_path, '-C', temp_dir], check=True)
                
                # Read the manifest.json to understand the structure
                manifest_path = Path(temp_dir) / 'manifest.json'
                if not manifest_path.exists():
                    self.logger.error("No manifest.json found in image tar")
                    return []
                
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)[0]  # Usually contains one entry
                
                image_layers = manifest.get('Layers', [])
                
                # Create layers output directory
                layers_dir = self.output_dir / 'layers'
                layers_dir.mkdir(exist_ok=True)
                
                # We need to map the delta layer IDs to the actual layer files in the tar
                # The manifest contains layer files, but we need to identify which ones
                # correspond to our delta layers
                
                # Read the config to get layer mapping
                config_file = manifest.get('Config')
                if config_file:
                    config_path = Path(temp_dir) / config_file
                    if config_path.exists():
                        with open(config_path, 'r') as f:
                            config_data = json.load(f)
                            
                        # Get the diff_ids from config which map to our layer IDs
                        config_layers = config_data.get('rootfs', {}).get('diff_ids', [])
                        
                        # Map delta layer IDs to manifest layer files
                        delta_layer_files = []
                        for delta_layer in delta_layers:
                            # Find the index of this layer in config_layers
                            for i, config_layer in enumerate(config_layers):
                                if config_layer == delta_layer:
                                    # This delta layer corresponds to manifest layer at index i
                                    if i < len(image_layers):
                                        delta_layer_files.append(image_layers[i])
                                        self.logger.debug(f"Mapped delta layer {delta_layer[:12]}... to file {image_layers[i]}")
                                        break
                        
                        # Extract only the delta layer files with index prefix
                        for i, layer_file in enumerate(delta_layer_files):
                            layer_path = Path(temp_dir) / layer_file
                            if layer_path.exists():
                                # Extract this layer to our output directory with index prefix
                                layer_name = layer_file.replace('/', '_')
                                indexed_layer_name = f"{i+1:02d}_{layer_name}"
                                output_layer_path = layers_dir / indexed_layer_name
                                
                                shutil.copy2(layer_path, output_layer_path)
                                extracted_layers.append(str(output_layer_path))
                                
                                self.logger.debug(f"Extracted delta layer {i+1}: {indexed_layer_name}")
                
                self.logger.info(f"Extracted {len(extracted_layers)} delta layer files")
                
        except Exception as e:
            self.logger.error(f"Failed to extract layers from tar: {e}")
        
        return extracted_layers
    
    def generate_report(self, delta_layers: List[str], delta_history: List[Dict], extracted_files: List[str]) -> None:
        """Generate a summary report of the extraction process."""
        report_path = self.output_dir / 'extraction_report.json'
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'base_image': self.base_image,
            'built_image': self.built_image,
            'delta_layers_count': len(delta_layers),
            'delta_layers': delta_layers,
            'delta_history': delta_history,
            'extracted_files': extracted_files,
            'output_directory': str(self.output_dir)
        }
        
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.logger.info(f"Extraction report saved to: {report_path}")
        
        # Also create a human-readable summary if requested
        if self.human_summary:
            summary_path = self.output_dir / 'summary.txt'
            with open(summary_path, 'w') as f:
                f.write("Docker Layer Delta Extraction Summary\n")
                f.write("=====================================\n\n")
                f.write(f"Timestamp: {report['timestamp']}\n")
                f.write(f"Base Image: {self.base_image}\n")
                f.write(f"Built Image: {self.built_image}\n\n")
                f.write(f"Delta Layers Found: {len(delta_layers)}\n\n")
                
                for i, (layer, history) in enumerate(zip(delta_layers, delta_history)):
                    f.write(f"Layer {i+1}:\n")
                    f.write(f"  ID: {layer}\n")
                    f.write(f"  Size: {history.get('Size', 0)} bytes\n")
                    f.write(f"  Created by: {history.get('CreatedBy', 'Unknown')}\n\n")
                
                f.write("Extracted Layer Blobs (in order):\n")
                for file_path in extracted_files:
                    f.write(f"  {file_path}\n")
                
                f.write("\nNote: Layer blobs are prefixed with index (01_, 02_, etc.) to preserve extraction order.\n")
                f.write("Extract each blob with: tar -xf <blob_file> -C <target_directory>\n")
            
            self.logger.info(f"Summary report saved to: {summary_path}")
    
    def run(self) -> None:
        """Main execution method."""
        self.logger.info("Starting Docker layer delta extraction...")
        
        try:
            # Step 1: Pull base image to ensure we have the latest version
            self.pull_base_image()
            
            # Step 2: Identify delta layers
            delta_layers, delta_history = self.identify_delta_layers()
            
            if not delta_layers:
                self.logger.warning("No delta layers found. The image might be identical to the base image.")
                return
            
            # Step 3: Save image as tar
            tar_path = self.save_image_as_tar()
            if not tar_path:
                self.logger.error("Failed to save image as tar")
                return
            
            # Step 4: Extract delta layers
            extracted_files = self.extract_layers_from_tar(tar_path, delta_layers)
            
            # Step 5: Generate report
            self.generate_report(delta_layers, delta_history, extracted_files)
            
            # Step 6: Cleanup tar file
            os.remove(tar_path)
            self.logger.info("Cleaned up temporary tar file")
            
            self.logger.info(f"Extraction completed successfully! Output in: {self.output_dir}")
            
        except Exception as e:
            self.logger.error(f"Extraction failed: {e}")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Extract delta layers from a Docker image build",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        'base_image',
        help='Base image tag (e.g., ubuntu:20.04)'
    )
    
    parser.add_argument(
        'built_image', 
        help='Built image tag to extract delta from'
    )
    
    parser.add_argument(
        '--output-dir',
        default='./delta_layers',
        help='Output directory for extracted layers (default: ./delta_layers)'
    )
    
    parser.add_argument(
        '--human',
        action='store_true',
        help='Generate human-readable summary report'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Create and run extractor
    extractor = DockerLayerExtractor(
        base_image=args.base_image,
        built_image=args.built_image,
        output_dir=args.output_dir,
        verbose=args.verbose,
        human_summary=args.human
    )
    
    extractor.run()


if __name__ == '__main__':
    main()