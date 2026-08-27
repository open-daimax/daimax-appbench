#!/usr/bin/env python3
"""
Shared utility functions for build system
"""

import os
import subprocess


class Colors:
    """ANSI color codes for terminal output"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_info(message):
    """Print info message"""
    print(f"{Colors.OKBLUE}ℹ {message}{Colors.ENDC}")


def print_success(message):
    """Print success message"""
    print(f"{Colors.OKGREEN}✓ {message}{Colors.ENDC}")


def print_warning(message):
    """Print warning message"""
    print(f"{Colors.WARNING}⚠ {message}{Colors.ENDC}")


def print_error(message):
    """Print error message"""
    print(f"{Colors.FAIL}✗ {message}{Colors.ENDC}")


def print_header(message):
    """Print header message"""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'=' * 60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{message}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'=' * 60}{Colors.ENDC}\n")


def run_command(cmd, cwd=None, check=True, capture_output=False, env=None, timeout=None):
    """Run shell command with environment variables"""
    try:
        if env is None:
            env = os.environ.copy()
        
        if capture_output:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                check=check,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout
            )
            return result.stdout.strip()
        else:
            result = subprocess.run(cmd, shell=True, cwd=cwd, check=check, env=env, timeout=timeout)
            return result.returncode == 0
    except subprocess.TimeoutExpired:
        print_error(f"Command timed out: {cmd}")
        return None if capture_output else False
    except subprocess.CalledProcessError as e:
        if capture_output:
            print_error(f"Command failed: {cmd}")
            if e.stderr:
                print_error(f"Error: {e.stderr}")
        return None if capture_output else False


def find_tool_in_path(tool_name, env=None):
    """Find tool in PATH"""
    result = run_command(f"which {tool_name}", capture_output=True, env=env, check=False)
    if result:
        print_success(f"Found {tool_name} in PATH: {result}")
        return result
    return None


def load_shell_environment():
    """Load environment variables from shell configuration files"""
    shell = os.environ.get('SHELL', '/bin/bash')
    shell_name = os.path.basename(shell)
    
    # Determine which shell config files to source
    config_files = []
    home = os.path.expanduser("~")
    
    if shell_name == 'zsh':
        config_files = [
            os.path.join(home, '.zshrc'),
            os.path.join(home, '.zshenv'),
            os.path.join(home, '.zprofile'),
        ]
    elif shell_name == 'bash':
        config_files = [
            os.path.join(home, '.bashrc'),
            os.path.join(home, '.bash_profile'),
            os.path.join(home, '.profile'),
        ]
    
    # Try to source shell config and export environment
    for config_file in config_files:
        if os.path.exists(config_file):
            try:
                # Use shell to source config and print environment
                cmd = f'{shell} -c "source {config_file} && env"'
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if result.returncode == 0:
                    # Parse environment variables
                    for line in result.stdout.split('\n'):
                        if '=' in line:
                            key, _, value = line.partition('=')
                            if key and not key.startswith('_'):
                                os.environ[key] = value
                    
                    print_success(f"Loaded shell environment from: {config_file}")
                    return True
            except Exception as e:
                print_warning(f"Failed to load {config_file}: {e}")
                continue
    
    return False