
import re
import unicodedata
import json

# pdfからテキストを抽出するためのライブラリ
import fitz  # PyMuPDF
import tempfile
from timeout_decorator import timeout, TimeoutError

# webサイトからテキストを抽出するためのライブラリ
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

class ExamTargetClass(object):
    """
    コンストラクタ
    ・base_target_url: 審査対象のURL
    ・base_json_path: 原本の遵守宣言のjsonファイルのパス
    メソッド
    ・exam_execute: 審査を実行する
    ・_is_PDF: URLがPDFかどうかを判定する
    ・_crawl_web: URLからテキストを抽出する
    ・_extract_text_from_pdf: PDFファイルからテキストを抽出する
    ・_extract_text_from_html: HTMLページからテキストを抽出する
    ・_format_text: テキストの標準化
    ・_compare: 条文の比較
    ・_content_in_target: コンテンツ部分が対象に含まれているかをチェックする
    ・_header_in_target: ヘッダー部分が対象にに含まれているかをチェックする
    ・_validate_text: テキストに含まれるプレースホルダー部分を正規表現に置き換え、他の部分が変更されていないかを確認する（支援機関名にちゃんと代入されているかのチェック）
    """
    def __init__(self, base_target_url, base_json_path='base.json'):
        self.base_target_url = base_target_url
        self.base_json_path = base_json_path
    
    def exam_execute(self):
        """
        審査を実行する
        """
        #pdfもしくはhtmlからテキストを抽出
        try:
            base_target_url = self.base_target_url
            self.is_PDF = self._is_PDF(base_target_url)
            if self.is_PDF:
                target_url = base_target_url
                raw_text = self._extract_text_from_pdf(target_url)
            else:
                is_PDF, target_url = self._crawl_web(base_target_url)
                if is_PDF:
                    raw_text = self._extract_text_from_pdf(target_url)
                else:
                    raw_text = self._extract_text_from_html(target_url)
        except TimeoutError:
            #print(f"次のURLでテキスト抽出がタイムアウトしました。 url:{self.base_target_url}")
            return "処理スキップ"
        except Exception as e:
            #print(f"テキスト抽出時のエラー: {e}")
            return "テキスト抽出エラー"

        # テキストの標準化
        try:
            formatted_text = self._format_text(raw_text)
        except Exception as e:
            #print(f"テキストの標準化中にエラーが発生しました: {e}")
            return "テキスト標準化エラー"

        # 条文の比較
        try:
            result = self._compare(formatted_text)
        except Exception as e:
            #print(f"条文の比較中にエラーが発生しました: {e}")
            return "条文比較エラー"

        return result
    
    def exam_all_urls(self):
        links = self._get_links_from_base()

        OK_list = []
        defect_list = []
        defect_number_list = []
        exception_list = []
        
        #print(f"審査対象のリンク数: {len(links)}")

        #進捗表示
        
        for link in links: 
            #print(f"審査中: {link}")
            try:
                status, defect_number = self._classify_one_url(link)
                if status == 1:
                    OK_list.append([link])
                elif status == 2:
                    defect_list.append([link])
                    defect_number_list.append(defect_number)
                else:
                    exception_list.append([link])
            except Exception as e:
                exception_list.append([link])
                #print(f"エラーが発生しました: {e}")


        final_status = 0
        result = {"final_status": final_status, "links": None, "missing_clauses": None}

        if OK_list:
            result["final_status"] = 1
            result["links"] = [OK[0] for OK in OK_list]
        elif defect_list:
            result["final_status"] = 2
            min_defect_index = min(range(len(defect_number_list)), key=lambda x: len(defect_number_list[x]))
            result["links"] = defect_list[min_defect_index]
            result["missing_clauses"] = defect_number_list[min_defect_index]
        else:
            result["final_status"] = 3

        return result

    def _get_links_from_base(self):
        base_url = self.base_target_url
        try:
            # ベースURLのHTMLを取得
            r = requests.get(base_url)
            soup = BeautifulSoup(r.content, "html.parser")

            # リンクを格納するリスト
            links = [base_url]

            # 全ての<a>タグを探索
            for a in soup.find_all("a", href=True):
                link = a.get("href")
                # 相対リンクを絶対リンクに変換
                full_url = urljoin(base_url, link)
                # 有効なリンクか確認（スキームがあるもの）
                parsed_url = urlparse(full_url)
                if parsed_url.scheme in ["http", "https"]:
                    links.append(full_url)

            return links

        except requests.RequestException as e:
            #print("Error fetching the page:", e)
            return []
        
    def _classify_one_url(self, url):
        """
        あるリンクの審査結果を分類する関数。
        1. 全てTrue
        2. ひとつ以上True（内容に不備がある）
        3. 全てFalse(おそらく遵守宣言のページやPDFではない)
        """
        result = self._one_url_execute(url)
        
        
        defect_number = []
        status = 0


        # resultは辞書のリストになっている
        # 全てのjudgeがOKの場合、ひとつ以上OKの場合（全てではない）、全てNGの場合
        # 1. 全てTrue
        if all([r["judge"] for r in result]):
            status = 1
        # 2. ひとつ以上True
        elif any([r["judge"] for r in result]):
            # 不備の内容を出力
            for r in result:
                if not r["judge"]:
                    defect_number.append(str(r["number"]))
            status = 2
        # 3. 全てFalse  
        else:
            status = 3
        return status, defect_number
    
    def _one_url_execute(self, target_url):
        """
        審査を実行する
        """
        #pdfもしくはhtmlからテキストを抽出
        try:
            self.is_PDF = self._is_PDF(target_url)
            if self.is_PDF:
                raw_text = self._extract_text_from_pdf(target_url)
            else:
                raw_text = self._extract_text_from_html(target_url)
        except TimeoutError:
            #print(f"次のURLでテキスト抽出がタイムアウトしました。 url:{target_url}")
            return "処理スキップ"
        except Exception as e:
            #print(f"テキスト抽出時のエラー: {e}")
            return "テキスト抽出エラー"

        # テキストの標準化
        try:
            formatted_text = self._format_text(raw_text)
        except Exception as e:
            #print(f"テキストの標準化中にエラーが発生しました: {e}")
            return "テキスト標準化エラー"

        # 条文の比較
        try:
            result = self._compare(formatted_text)
        except Exception as e:
            #print(f"条文の比較中にエラーが発生しました: {e}")
            return "条文比較エラー"

        return result
    
    def _is_PDF(self, file_path):
        #拡張子で判定
        if file_path.endswith('.pdf'):
            return True
        else:
            return False

    def _crawl_web(self, base_target_url):
        """
        元々のurlから遵守宣言の記載のあるurlを返す
        """
        is_PDF = False
        return is_PDF, base_target_url

    @timeout(5)
    def _extract_text_from_pdf(self, url, reader='fitz'):
        """PDFファイルからテキストを抽出する関数。

        Args:
            pdf_path: PDFファイルのパス。
            reader: PDFリーダーの選択 ('pdfminer', 'pypdf2', 'pdfplumber', 'fitz')。

        Returns:
            PDFファイルのテキスト内容。
        """

        try:
            # PDFファイルをURLからダウンロード
            response = requests.get(url)
            response.raise_for_status()  # エラーチェック

            # 一時ファイルにPDFを保存
            with tempfile.NamedTemporaryFile(suffix=".pdf") as temp_pdf:
                temp_pdf.write(response.content)
                temp_pdf.flush()  # データをディスクに書き込む

                # 一時ファイルをfitzで開き、テキスト抽出
                text = ''
                doc = fitz.open(temp_pdf.name)
                for page_num in range(doc.page_count):
                    page = doc.load_page(page_num)
                    text += page.get_text()
                doc.close()

            return text

        except Exception as e:
            #print(f"オンラインPDFファイルのテキスト抽出に失敗しました: {e}")
            raise e

    @timeout(5)
    def _extract_text_from_html(self, url):
        """HTMLページからテキストを抽出する関数。

        Args:
            url: HTMLページのURL。

        Returns:
            HTMLページのテキスト内容。
        """
        try:
            response = requests.get(url)
            response.encoding = 'utf-8' 
            response.raise_for_status()  # HTTPエラーが発生した場合は例外を発生させる

            soup = BeautifulSoup(response.content, 'html.parser')
            text = soup.get_text(separator='\n')  # HTMLからテキストを抽出し、改行で区切る

            return text
        
        except Exception as e:
            #print(f"オンラインHTMLページのテキスト抽出に失敗しました: {e}")
            raise e

    def _format_text(self, text):
        # 改行コードを統一
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        # 行ごとに分割
        lines = text.split('\n')

        formatted_text = ''

        # 削除対象の文言リスト
        removal_phrases = [
            '(別紙1)HP掲載・顧客説明の際の参考資料',
            '中小M&Aガイドライン(第3版)遵守の宣言について',
        ]

        for line in lines:
            # 空白、全角スペースを削除
            line = line.replace(' ', '').replace('　', '').replace('．', '').replace('·', '').replace(' ', '').replace('・', '').replace('、', '').replace('。', '')
            line = ''.join(char for char in line if unicodedata.category(char)[0] != 'C')
            line= unicodedata.normalize('NFKC', line)
            if not line or any(phrase == line for phrase in removal_phrases):
                continue  # 空行、削除対象の行はスキップ
            
            formatted_text += line

        return formatted_text

    def _compare(self, target_text):
        # jsonファイルの読み込み
        json_path = self.base_json_path
        with open(json_path, 'r', encoding='utf-8') as f:
            base_guideline = json.load(f)

        result_header = self._header_in_target(base_guideline['header'], target_text)
        result_content = self._content_in_target(base_guideline['content'], target_text)

        
        combined_results = [result_header]  # headerをリストの先頭に
        combined_results.extend(result_content)  # contentの要素を後ろに追加

        return combined_results

    def _content_in_target(self, base_items, target_text):
        """
        Checks if each content within base_items, including nested middle, small, and small-small levels, 
        is included in the target_text.
        """
        results = []
        
        
        for item in base_items:
            # Check 'large' level content
            number = item['large_number']
            content_text = item['text']
            is_in_target = content_text in target_text
            results.append({'number': number, 'base_content': content_text, 'judge': is_in_target})
            
            # Check 'middle' level content if it exists
            if 'middle_content' in item:
                for middle_item in item['middle_content']:
                    middle_number = middle_item['middle_number']
                    middle_text = middle_item['middle_text']
                    is_in_target = middle_text in target_text
                    results.append({'number': f"{number}.{middle_number}", 'base_content': middle_text, 'judge': is_in_target})
                    
                    # Check 'small' level content if it exists
                    if 'small_content' in middle_item:
                        for small_item in middle_item['small_content']:
                            if 'small_text' in small_item:
                                small_number = small_item['small_number']
                                small_text = small_item['small_text']
                                is_in_target = small_text in target_text
                                results.append({'number': f"{number}.{middle_number}.{small_number}", 'base_content': small_text, 'judge': is_in_target})
                            
                            # Check 'small-small' level content if it exists
                            if 'small_small_content' in small_item:
                                for small_small_item in small_item['small_small_content']:
                                    if 'small_small_text' in small_small_item:
                                        small_small_number = small_small_item['small_small_number']
                                        small_small_text = small_small_item['small_small_text']
                                        is_in_target = small_small_text in target_text
                                        results.append({'number': f"{number}.{middle_number}.{small_number}.{small_small_number}", 'base_content': small_small_text, 'judge': is_in_target})
            
            # Check 'asterisk' content if it exists
            if 'asterisk_content' in item:
                for asterisk_item in item['asterisk_content']:
                    if 'asterisk_text' in asterisk_item:
                        asterisk_number = asterisk_item['asterisk_number']
                        asterisk_text = asterisk_item['asterisk_text']
                        is_in_target = asterisk_text in target_text
                        results.append({'number': f"{number}*{asterisk_number}", 'base_content': asterisk_text, 'judge': is_in_target})

            
            # Check nested asterisk content in 'middle' level
            if 'middle_content' in item:
                for middle_item in item['middle_content']:
                    if 'asterisk_content' in middle_item:
                        for asterisk_item in middle_item['asterisk_content']:
                            if 'asterisk_text' in asterisk_item:
                                asterisk_number = f"{number}.{middle_item['middle_number']}*{asterisk_item['asterisk_number']}"
                                asterisk_text = asterisk_item['asterisk_text']
                                is_in_target = asterisk_text in target_text
                                results.append({'number': asterisk_number, 'base_content': asterisk_text, 'judge': is_in_target})

                    # Check nested asterisk content in 'small' level
                    if 'small_content' in middle_item:
                        for small_item in middle_item['small_content']:
                            if 'asterisk_content' in small_item:
                                for asterisk_item in small_item['asterisk_content']:
                                    if 'asterisk_text' in asterisk_item:
                                        asterisk_number = f"{number}.{middle_item['middle_number']}.{small_item['small_number']}*{asterisk_item['asterisk_number']}"
                                        asterisk_text = asterisk_item['asterisk_text']
                                        is_in_target = asterisk_text in target_text
                                        results.append({'number': asterisk_number, 'base_content': asterisk_text, 'judge': is_in_target})

                            # Check nested asterisk content in 'small-small' level
                            if 'small_small_content' in small_item:
                                for small_small_item in small_item['small_small_content']:
                                    if 'asterisk_content' in small_small_item:
                                        for asterisk_item in small_small_item['asterisk_content']:
                                            if 'asterisk_text' in asterisk_item:
                                                asterisk_number = f"{number}.{middle_item['middle_number']}.{small_item['small_number']}.{small_small_item['small_small_number']}*{asterisk_item['asterisk_number']}"
                                                asterisk_text = asterisk_item['asterisk_text']
                                                is_in_target = asterisk_text in target_text
                                                results.append({'number': asterisk_number, 'base_content': asterisk_text, 'judge': is_in_target})
        
        return results
   
    def _header_in_target(self, base_header, target_text):
        """
        base_itemsの各contentがtarget_textに含まれているかをチェックする関数
        """

        # 各contentがtarget_textに含まれているかをチェック
        is_in_target = self._validate_text(base_header, target_text)
        results = {
            'number': 0,
            'judge': is_in_target
            }

        return results
    
    def _validate_text(self, base_text,text):
        # (M&A支援機関名)の置き換えを確認
        
        if "(M&A支援機関名)" in text:
            print("(M&A支援機関名)が置き換えられていません")
            return False

        # プレースホルダー部分を正規表現に置き換え
        pattern = re.escape(base_text).replace(re.escape("(M&A支援機関名)"), ".+")
        
        # 他の部分が変更されていないかを確認
        match = re.search(pattern, text)

        if match:  
            return True
        else:
            return False

def one_test(base_url):
    base_json_path = 'base.json'
    exam = ExamTargetClass(base_url, base_json_path)
    final_status, right_links, target_defect_number = exam.exam_all_urls()
    print("=====================================")
    if final_status == 1:
        print("審査結果：OK")
        print("以下のリンクの遵守宣言がOKです。")
        for right_link in right_links:
            print(right_link)
    elif final_status == 2:
        print("審査結果：内容不備あり")
        print("以下のリンクの遵守宣言に不備があります。")
        print(target_defect_number[0])
        print("以下の条文が見当たりませんでした。")
        for defect_number in target_defect_number[1]:
            print(defect_number)
    else:
        print("審査結果：動線不明")
    print("=====================================")

def test_all():
    # urlをurls.txtから読み込む
    urls_path = 'urls.txt'
    with open(urls_path) as f:
        urls = f.readlines()
    urls = [url.strip() for url in urls]
    for url in urls:
        one_test(url)

if __name__ == "__main__":
    test_all()
