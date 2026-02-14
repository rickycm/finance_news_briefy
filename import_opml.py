import re
import yaml
from pathlib import Path

# OPML Content (truncated in thought, but I have access to file path)
# I will read from the file path I just read.
OPML_PATH = "/home/ricky/.openclaw/media/inbound/file_19---ee027a18-15ee-47a7-ad34-08ebecd0b421"
YAML_PATH = "/home/ricky/webservice/finance_news_briefy/config/rss_sources.yaml"

def import_opml():
    # Read YAML
    with open(YAML_PATH, 'r') as f:
        config = yaml.safe_load(f) or {}
    
    existing_urls = {s['url'] for s in config.get('sources', [])}
    existing_ids = {s['id'] for s in config.get('sources', [])}
    
    # Read OPML
    with open(OPML_PATH, 'r') as f:
        opml_content = f.read()
    
    # Simple regex parse
    # <outline type="rss" text="..." title="..." xmlUrl="..." htmlUrl="..."/>
    pattern = re.compile(r'<outline[^>]+title="([^"]+)"[^>]+xmlUrl="([^"]+)"')
    matches = pattern.findall(opml_content)
    
    new_sources = []
    
    for title, url in matches:
        if url in existing_urls:
            continue
            
        # Generate ID
        # sanitize title to id
        safe_id = re.sub(r'[^a-zA-Z0-9]', '_', title).lower()
        while safe_id in existing_ids:
            safe_id += "_1"
            
        source = {
            "id": safe_id,
            "name": title,
            "url": url,
            "enabled": True,
            "language": "en", # Defaulting to EN for this list
            "translate": True
        }
        
        new_sources.append(source)
        existing_urls.add(url)
        existing_ids.add(safe_id)
        
    # Append
    if new_sources:
        if 'sources' not in config:
            config['sources'] = []
        config['sources'].extend(new_sources)
        
        with open(YAML_PATH, 'w') as f:
            yaml.dump(config, f, allow_unicode=True, sort_keys=False)
            
        print(f"Imported {len(new_sources)} feeds.")
    else:
        print("No new feeds to import.")

import_opml()
