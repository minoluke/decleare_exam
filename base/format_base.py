import json
import unicodedata

def cleanse_text(text):
    text = text.replace(' ', '').replace('　', '').replace('．', '').replace('·', '').replace('・', '').replace('、', '').replace('。', '')
    text = unicodedata.normalize('NFKC', text)
    return text

# Modify cleanse_json_content function to handle asterisk_content at all nested levels
def cleanse_json_content(content):
    for item in content:
        # Cleanse main text
        item['text'] = cleanse_text(item['text'])
        
        # Cleanse middle content if it exists
        if 'middle_content' in item:
            for middle_item in item['middle_content']:
                middle_item['middle_text'] = cleanse_text(middle_item['middle_text'])
                
                # Cleanse small content if it exists
                if 'small_content' in middle_item:
                    for small_item in middle_item['small_content']:
                        if 'small_text' in small_item:
                            small_item['small_text'] = cleanse_text(small_item['small_text'])
                        
                        # Cleanse small_small_content if it exists
                        if 'small_small_content' in small_item:
                            for small_small_item in small_item['small_small_content']:
                                if 'small_small_text' in small_small_item:
                                    small_small_item['small_small_text'] = cleanse_text(small_small_item['small_small_text'])

                        # Cleanse asterisk content in small_content
                        if 'asterisk_content' in small_item:
                            for asterisk_item in small_item['asterisk_content']:
                                if 'asterisk_text' in asterisk_item:
                                    asterisk_item['asterisk_text'] = cleanse_text(asterisk_item['asterisk_text'])

                # Cleanse asterisk content in middle_content
                if 'asterisk_content' in middle_item:
                    for asterisk_item in middle_item['asterisk_content']:
                        if 'asterisk_text' in asterisk_item:
                            asterisk_item['asterisk_text'] = cleanse_text(asterisk_item['asterisk_text'])

        # Cleanse asterisk content in main level
        if 'asterisk_content' in item:
            for asterisk_item in item['asterisk_content']:
                if 'asterisk_text' in asterisk_item:
                    asterisk_item['asterisk_text'] = cleanse_text(asterisk_item['asterisk_text'])

file_path = 'base_before.json'
with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# Reapply the cleansing process to the updated JSON data
data['header'] = cleanse_text(data['header'])
cleanse_json_content(data['content'])

# Save the final cleansed data to a new JSON file
output_path = 'base_after.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

