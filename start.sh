#!/bin/bash

# LLM Model Manager start script

# Color definitions
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  LLM Model Manager${NC}"
echo -e "${BLUE}========================================${NC}"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python3 not found${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Python3 installed"

# Check the config file
if [ ! -f "config/services.json" ]; then
    echo -e "${YELLOW}⚠${NC} Config file not found, creating from example..."
    if [ -f "config/services.json.example" ]; then
        cp config/services.json.example config/services.json
        echo -e "${YELLOW}Edit config/services.json to configure your services${NC}"
        exit 1
    else
        echo -e "${RED}Error: config example not found${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✓${NC} Config file present"

# Check dependencies
echo -e "${BLUE}Checking Python dependencies...${NC}"
pip3 list | grep -q flask || {
    echo -e "${YELLOW}Installing dependencies...${NC}"
    pip3 install -r requirements.txt
}

echo -e "${GREEN}✓${NC} Dependencies installed"

# Set the default port
PORT=${PORT:-9000}
HOST=${HOST:-0.0.0.0}

echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Starting the service...${NC}"
echo -e "${BLUE}URL: http://${HOST}:${PORT}${NC}"
echo -e "${BLUE}========================================${NC}"

# Start the app
python3 app.py
