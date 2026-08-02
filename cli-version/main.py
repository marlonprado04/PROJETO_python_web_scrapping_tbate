import cloudscraper
from bs4 import BeautifulSoup
import os
import re
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import zipfile
from tqdm import tqdm
import requests
import threading
import html

# Tenta importar a biblioteca para gerar EPUB
try:
    from ebooklib import epub
except ImportError:
    print("A biblioteca 'EbookLib' é necessária para a opção de gerar EPUB.")
    print("Instale-a executando no terminal: pip install EbookLib")
    exit()

BASE_URL = "https://centralnovel.com/shadow-slave-capitulo-"

# Cria uma sessão estável simulando o Chrome
session = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
)

MAX_CONCURRENT = 10
MAX_RETRIES = 4
MIN_DELAY = 2
MAX_DELAY = 5
file_lock = threading.Lock()

def limpar_nome_arquivo(nome):
    return re.sub(r'[\/*?:"<>|]', "", nome).strip()

def extrair_conteudo(soup):
    root = soup.find("div", class_="epcontent entry-content")
    if not root:
        return ""
    for extra in root.find_all(["script", "style", "ins", "div"], class_=re.compile(r"ads|social|shared", re.I)):
        extra.decompose()
    texto = root.get_text(separator="\n")
    return "\n\n".join([linha.strip() for linha in texto.split("\n") if linha.strip()])

def baixar_pagina(url):
    for tentativa in range(MAX_RETRIES):
        try:
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
            r = session.get(url, timeout=20)
            if r.status_code == 200:
                return r
            if r.status_code in (403, 429, 503):
                espera = min((2 ** tentativa) * 10, 60)
                tqdm.write(f"-> Bloqueio {r.status_code} na URL: {url.split('-')[-1]}. Esperando {espera}s...")
                time.sleep(espera)
                continue
            return r
        except requests.exceptions.RequestException:
            tqdm.write("-> Falha de conexão. Tentando novamente...")
            time.sleep(10)
    return None

def fetch_capitulo(cap_id):
    url = f"{BASE_URL}{cap_id}"
    try:
        r = baixar_pagina(url)
        if not r or r.status_code != 200:
            return (cap_id, str(cap_id), "ERRO", f"ERRO_{cap_id}.txt", f"Erro ao acessar {url}")

        soup = BeautifulSoup(r.text, "html.parser")  
        titulo_el = soup.find("h1", class_="entry-title")  
        serie_el = soup.find("div", class_="cat-series")  
        
        titulo_bruto = titulo_el.get_text().strip() if titulo_el else f"Capítulo {cap_id}"  
        serie = limpar_nome_arquivo(serie_el.get_text()) if serie_el else "Shadow Slave"  

        match = re.search(r"(\d+)", str(cap_id))  
        num = match.group(1).zfill(5) if match else str(cap_id)  

        titulo_completo = f"{titulo_bruto} - {serie}"
        nome_arquivo = limpar_nome_arquivo(f"{titulo_completo}.txt")  
        
        texto_puro = extrair_conteudo(soup)
        conteudo = f"{titulo_completo}\n\n{texto_puro}\n"  
        
        return (cap_id, num, titulo_completo, nome_arquivo, conteudo)  
    except Exception as e:  
        return (cap_id, str(cap_id), "ERRO", f"ERRO_{cap_id}.txt", str(e))

def unificar_arquivos():
    pasta = input("Digite o caminho da pasta com os arquivos .txt: ").strip()
    if not os.path.exists(pasta):
        print("Pasta não encontrada.")
        return

    saida = input("Nome do arquivo final (ex: livro_completo.txt): ").strip()  
    arquivos = [f for f in os.listdir(pasta) if f.endswith(".txt")]  

    arquivos.sort(key=lambda f: [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', f)])  

    with open(saida, "w", encoding="utf-8") as outfile:  
        for fname in tqdm(arquivos, desc="Unificando"):  
            with open(os.path.join(pasta, fname), "r", encoding="utf-8") as infile:  
                outfile.write(infile.read() + "\n" + "="*40 + "\n\n")  
    print(f"Sucesso! Arquivo gerado: {saida}")

# ======== FILTRO DE SEGURANÇA PARA O EPUB ========
def limpar_xml(texto):
    """Remove sujeira invisível do site que faz o leitor de EPUB crachar."""
    if not texto: return ""
    # Remove caracteres de controle ASCII que quebram o parser XML
    texto = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', texto)
    # Protege símbolos do sistema da novel (< e >)
    return html.escape(texto)
# =================================================

def main():
    print("1 = Baixar (TXT Individual)")
    print("2 = Baixar (ZIP)")
    print("3 = Unificar pasta TXT")
    print("4 = Baixar e Unificar em EPUB (Ideal para Kindle) [NOVO]")

    opcao = input("Escolha uma opção: ").strip()  

    if opcao == "3":  
        unificar_arquivos()  
        return  

    inicio = int(input("Capítulo inicial: "))  
    fim = int(input("Capítulo final: "))  

    pasta = "Capitulos"
    caminho_zip = "novels.zip"
    nome_epub = "livro_completo.epub"

    if opcao == "1":  
        pasta = input("Pasta para salvar: ").strip() or "Capitulos"  
        os.makedirs(pasta, exist_ok=True)  
    elif opcao == "2":  
        caminho_zip = input("Nome do arquivo ZIP: ").strip() or "novels.zip"  
        if not caminho_zip.endswith(".zip"): caminho_zip += ".zip"  
    elif opcao == "4":
        nome_epub = input("Nome do arquivo EPUB (ex: livro.epub): ").strip() or "livro_completo.epub"
        if not nome_epub.endswith(".epub"): nome_epub += ".epub"

    resultados_epub = []

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:  
        futures = {executor.submit(fetch_capitulo, c): c for c in range(inicio, fim + 1)}  
        for future in tqdm(as_completed(futures), total=(fim - inicio + 1), desc="Processando"):  
            cap_id, num, titulo, nome, conteudo = future.result()  
            
            if "ERRO" in nome:
                tqdm.write(f"-> Falha ao processar capítulo {cap_id}")
                continue

            with file_lock:  
                if opcao == "1":  
                    with open(os.path.join(pasta, nome), "w", encoding="utf-8") as f:  
                        f.write(conteudo)  
                elif opcao == "2":  
                    with zipfile.ZipFile(caminho_zip, "a", zipfile.ZIP_DEFLATED) as zipf:  
                        zipf.writestr(nome, conteudo)  
                elif opcao == "4":
                    resultados_epub.append((num, titulo, conteudo))

    if opcao == "4" and resultados_epub:
        print("\nMontando arquivo EPUB...")
        
        resultados_epub.sort(key=lambda x: x[0])

        book = epub.EpubBook()
        book.set_title("Shadow Slave")
        book.set_language("pt")

        chapters = []
        for num, titulo, texto in tqdm(resultados_epub, desc="Gerando Capítulos EPUB"):
            c = epub.EpubHtml(title=titulo, file_name=f'cap_{num}.xhtml', lang='pt')
            
            linhas = texto.split("\n\n")
            if linhas and linhas[0].strip() == titulo.strip():
                linhas = linhas[1:]

            titulo_limpo = limpar_xml(titulo)
            
            # Envelopado de forma limpa, sem reescrever tags de sistema
            html_content = f"<div>\n<h1>{titulo_limpo}</h1>\n"
            
            conteudo_valido = False
            for linha in linhas:
                linha_limpa = linha.strip()
                if linha_limpa:
                    html_content += f"<p>{limpar_xml(linha_limpa)}</p>\n"
                    conteudo_valido = True
            
            # Trava de segurança: impede que a biblioteca leia um capítulo como "Vazio"
            if not conteudo_valido:
                html_content += "<p>Aviso: O texto deste capítulo não pôde ser carregado do site.</p>\n"
                
            html_content += "</div>"

            # Passando o texto limpo para a biblioteca criar o HTML estrutural final
            c.content = html_content
            
            book.add_item(c)
            chapters.append(c)

        book.toc = tuple(chapters)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        
        book.spine = chapters

        # Bloco final com proteção de erro
        try:
            epub.write_epub(nome_epub, book, {})
            print(f"Sucesso! Arquivo EPUB gerado: {nome_epub}")
        except Exception as e:
            print(f"\nFalha ao salvar o EPUB. Erro retornado: {e}")

    print("\nConcluído!")

if __name__ == "__main__":
    main()
