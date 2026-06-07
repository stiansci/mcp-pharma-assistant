import os
import time
import mmap
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from io import BytesIO

# Librerie esterne
from lxml import etree as ET
import polars as pl
from tqdm import tqdm

# --- CONFIGURAZIONE ---

# Utilizziamo __file__ per rendere i percorsi relativi alla posizione dello script
base_dir: str = os.path.dirname(__file__)
RAW_DIR: str = os.path.join(base_dir, "../0_raw_files")
OUTPUT_DIR: str = os.path.join(base_dir, "2_drugbank", "parquet_files")

CONFIG: dict[str, str | int] = {
    "xml_file": os.path.join(RAW_DIR, "full database.xml"),
    "output_dir": OUTPUT_DIR,
    "chunk_size": 64 * 1024 * 1024, # Dimensione del chunk in byte = 64MB (1024 Byte = 1KB x 1024 = 1MB)
    "ns": {'db': 'http://www.drugbank.ca'} # Mappa il namespace XML, identifica in modo univoco i tag
}

# Definizione degli schemi Polars per garantire consistenza nei tipi di dato (anche se un chunk dovesse risultare vuoto)
SCHEMAS: dict[str, pl.Schema] = {
    "drugs": {
        "drugbank_id": pl.Utf8, 
        "name": pl.Utf8, 
        "type": pl.Utf8, 
        "state": pl.Utf8
    },
    "interactions": {
        "source_drug_id": pl.Utf8, 
        "target_drug_id": pl.Utf8, 
        "description": pl.Utf8
    },
    "synonyms": {
        "drugbank_id": pl.Utf8, 
        "synonym": pl.Utf8
    },
    "atc_codes": {
        "drugbank_id": pl.Utf8, 
        "atc_code": pl.Utf8
    }
}

# --- FUNZIONI DI SUPPORTO ---

def find_chunk_offsets(filepath: str, chunk_size: int) -> list[tuple[int, int]]:
    """
    Scansiona il file XML utilizzando memory mapping per trovare gli offset sicuri 
    per la parallelizzazione. I chunk devono essere divisi esattamente tra la fine 
    di un tag </drug> e l'inizio del successivo. Così evitiamo di troncare un record.

    Args:
        filepath (str): Percorso del file XML.
        chunk_size (int): Dimensione target del chunk in byte.

    Returns:
        list[tuple[int, int]]: Una lista di tuple (start_byte, end_byte).
    """
    offsets: list[tuple[int, int]] = [] # (start_byte, end_byte)
    file_size: int = os.path.getsize(filepath) # Dimensione del file in byte
    
    with open(filepath, "rb") as f:
        # lazy loading: mmap ci permette di leggere il file un pezzetto alla volta senza caricarlo tutto in RAM.
        with mmap.mmap(f.fileno(), length=0, access=mmap.ACCESS_READ) as mm: 
            # fileno() restituisce il File Descriptor, un ID numerico usato dal sistema operativo per gestire il file aperto
            # length=0 prende tutto il file, access=READ è per sola lettura
            
            # Cerchiamo '<drug ' (con spazio) o '<drug>' per identificare l'inizio di un record.
            # Questo evita di confondersi con tag come <drugbank-id> o <drug-interaction>.
            start_tag = b'<drug ' # b = modalità binaria
            end_tag = b'</drug>'
            
            # Troviamo il primo vero tag <drug> per saltare l'header XML
            current_pos: int = mm.find(start_tag)
            
            # Meccanismo di fallback: se non trova '<drug ', prova '<drug>' (senza attributi)
            if current_pos == -1: # sentinel value  
                current_pos = mm.find(b'<drug>')
            
            if current_pos == -1: 
                return [] # Se non trova nessun tag <drug>, restituisce una lista vuota
            
            while current_pos < file_size: # Finché non raggiungiamo la fine del file
                target_end: int = min(current_pos + chunk_size, file_size) 
                
                if target_end >= file_size:
                    offsets.append((current_pos, file_size))
                    break
                
                # Cerchiamo la chiusura reale </drug> DOPO il target_end per non troncare il record
                actual_end: int = mm.find(end_tag, target_end)
                # end_tag = cosa cerca
                # target_end = da quale posizione inizia la ricerca 
                
                if actual_end == -1:
                    # Nessuna chiusura trovata, prendiamo tutto fino alla fine
                    offsets.append((current_pos, file_size))
                    break
                
                # Includiamo la lunghezza del tag di chiusura
                actual_end += len(end_tag)
                
                offsets.append((current_pos, actual_end))
                current_pos = actual_end
                
    return offsets

def process_chunk(args: tuple[int, int, str]) -> dict[str, pl.DataFrame]:
    """
    Funzione Worker eseguita in parallelo.
    1. Legge una porzione di byte dal file.
    2. Avvolge i dati in un root fittizio per renderlo XML valido.
    3. Parsa i dati ed estrae le informazioni in DataFrame Polars.

    Args:
        args (tuple): Contiene (start_offset, end_offset, filepath).

    Returns:
        dict[str, pl.DataFrame]: Un dizionario contenente i DataFrame parziali 
                                 per drugs, interactions, synonyms, atc_codes.
    """
    start, end, filepath = args
    ns = CONFIG["ns"]
    
    # Buffer in-memory: l'append su liste Python è O(1), mentre su DataFrame richiede riallocazione memoria costosa.    
    data = {k: [] for k in SCHEMAS.keys()}
    
    # Un chunk contiene molti tag <drug> consecutivi ma nessun tag radice.
    # Creiamo artificialmente una radice (<root>) all'inizio e alla fine per rendere valido l'XML.
    fake_root_start = b'<root xmlns="http://www.drugbank.ca" xmlns:db="http://www.drugbank.ca">'
    fake_root_end = b'</root>'

    try:
        with open(filepath, "rb") as f:
            f.seek(start) # Sposta il cursore di lettura direttamente al byte di inizio del chunk
            content = f.read(end - start) # Legge il contenuto del chunk

        # Duck Typing: BytesIO "traveste" i nostri byte in memoria facendoli sembrare un file vero, 
        # perché il parser XML accetta solo oggetti simili a file in input.        
        stream = BytesIO(fake_root_start + content + fake_root_end)
        
        # Iterparse legge l'XML un elemento alla volta, così non occupiamo troppa memoria.
        context = ET.iterparse(stream, events=('end',), tag="{http://www.drugbank.ca}drug", recover=True)
        
        # Scartiamo event (la costante 'end') perché non ci interessa il tag di apertura.
        # elem contiene l'elemento XML corrente.

        for _, elem in context:
            # Estrazione id principale (primary="true").
            # Se manca, usiamo un ID qualsiasi come fallback.
            # Findtext restituisce il testo all'interno del tag specificato.
            db_id = elem.findtext('db:drugbank-id[@primary="true"]', namespaces=ns)
            if not db_id:
                db_id = elem.findtext('db:drugbank-id', namespaces=ns)
            
            # Estrazione nome del farmaco
            name = elem.findtext('db:name', namespaces=ns)
            
            if db_id and name:
                # 1. Tabella Farmaci (Drugs)
                d_type = elem.get('type', None) # Es. Biotech vs Small Molecule
                d_state = elem.findtext('db:state', namespaces=ns) # Es. Solid, Liquid

                data["drugs"].append((db_id, name, d_type, d_state))
                
                # 2. Tabella Interazioni
                # Findall restituisce una lista di tutti i tag specificati.
                # Entra nel tag contenitore <drug-interactions> e itera su ogni singola <drug-interaction>
                for i in elem.findall('db:drug-interactions/db:drug-interaction', namespaces=ns): 
                    data["interactions"].append((
                        db_id,
                        i.findtext('db:drugbank-id', namespaces=ns),
                        i.findtext('db:description', namespaces=ns)
                    ))
                
                # 3. Sinonimi
                for s in elem.findall('db:synonyms/db:synonym', namespaces=ns):
                    if s.text:
                        data["synonyms"].append((db_id, s.text))
                
                # 4. Codici ATC
                for a in elem.findall('db:atc-codes/db:atc-code', namespaces=ns):
                    code = a.get('code')
                    if code:
                        data["atc_codes"].append((db_id, code))
            
            # Anche con iterparse, lxml mantiene in memoria i nodi passati se non vengono rimossi esplicitamente.
            elem.clear() # Rimuove il nodo appena processato
            while elem.getprevious() is not None: # Rimuove i predecessori
                del elem.getparent()[0]
        
        stream.close() # Chiude lo stream BytesIO
        del context # Rimuove l'oggetto iterparse per liberare memoria

    except Exception as e:
        print(f"[!] Errore nel chunk {start}-{end}: {e}")
        # Continua e restituisce i dati raccolti finora (o vuoti)

    # Conversione in DataFrame Polars: sfrutta il formato Arrow per una serializzazione efficiente (zero-copy) tra processi.
    # Sfruttiamo una dictionary comprehension per creare i DataFrame in modo efficiente.
    # Orient="row" indica che i dati sono in formato righe (default).
    return {
        key: pl.DataFrame(rows, schema=SCHEMAS[key], orient="row") 
        for key, rows in data.items()
    }

# --- FUNZIONE PRINCIPALE ---

def main() -> None:
    """
    Funzione principale che orchestra l'intera pipeline ETL parallela.
    1. Calcola gli offset.
    2. Distribuisce i chunk ai worker.
    3. Aggrega i risultati.
    4. Deduplica e salva in formato Parquet.
    """
    start_time = time.time()
    print(f"--- Pipeline DrugBank ---")
    
    if not os.path.exists(CONFIG["xml_file"]):
        print(f"ERRORE: File mancante: {CONFIG['xml_file']}")
        return

    os.makedirs(CONFIG["output_dir"], exist_ok=True)
    # esist_ok=True: se la directory esiste già, non solleva un errore.

    print("1. Calcolo offset per parallelizzazione...")
    offsets = find_chunk_offsets(CONFIG["xml_file"], CONFIG["chunk_size"])
    print(f"   -> File diviso in {len(offsets)} chunks.")
    
    # Preparazione argomenti per i worker
    # Creazione una lista di tuple (start, end, filename) per ogni chunk.
    chunk_args: list[tuple[int, int, str]] = [(s, e, CONFIG["xml_file"]) for s, e in offsets]
    
    # È una variabile buffer che accumula man mano i DataFrame di ciascun chunk.
    results_buffer: dict[str, list[pl.DataFrame]] = {k: [] for k in SCHEMAS.keys()}
    
    print("2. Elaborazione parallela (Parsing XML)...")
    # ProcessPoolExecutor usa tutti i processori del computer per fare il lavoro più velocemente.
    with ProcessPoolExecutor() as executor:
        # Submit invia i task ai worker. 
        # Un Future è un placeholder per un risultato non ancora disponibile.
        futures: list[Future[dict[str, pl.DataFrame]]] = [executor.submit(process_chunk, arg) for arg in chunk_args]
        
        # TQDM visualizza una barra di progresso basata sul completamento dei future
        # as_completed restituisce i risultati in ordine di completamento.
        for future in tqdm(as_completed(futures), total=len(futures), desc="Processing", unit="chk"):
            try:
                chunk_dfs: dict[str, pl.DataFrame] = future.result()
                # Variabile temporanea che contiene i DataFrame parziali.
                # Viene sovrascritta ogni volta che viene inviato un nuovo risultato.

                for key, df in chunk_dfs.items():
                    if not df.is_empty():
                        results_buffer[key].append(df)
            except Exception as e:
                print(f"Errore critico in un worker: {e}")

    print("\n3. Aggregazione, Deduplicazione e Salvataggio...")
    
    for key, df_list in results_buffer.items():
        if df_list:
            # Concatenazione veloce di tutti i pezzi
            final_df = pl.concat(df_list)
            
            # --- LOGICA DI DEDUPLICAZIONE ---
            # Il database DrugBank ha dei duplicati vuoti che fanno riferimento allo stesso ID.
            # Si tratta di stubs, cioè record vuoti che fanno riferimento ad un ID esistente (Master).
            
            if key == "drugs":
                # Ordiniamo per 'type' decrescente (nulls_last).
                # Le righe con dati andranno in alto.
                # Le righe vuote (stubs) andranno in basso.
                # Mantenendo la prima occorrenza, salviamo il record più ricco.
                final_df = final_df.sort("type", descending=True, nulls_last=True)
                final_df = final_df.unique(subset=["drugbank_id"], keep="first")
                
            elif key == "interactions":
                # Rimuove righe duplicate identiche (se presenti)
                final_df = final_df.unique()
            
            # Le altre tabelle (synonyms, atc) beneficiano di una semplice rimozione duplicati completi
            elif key in ["synonyms", "atc_codes"]:
                 final_df = final_df.unique()

            output_path = os.path.join(CONFIG["output_dir"], f"{key}.parquet")
            final_df.write_parquet(output_path)
            
            print(f"   -> {key.ljust(15)}: {str(final_df.height).rjust(8)} righe uniche salvate.")
        else:
            print(f"   -> {key.ljust(15)}: Nessun dato estratto.")

    elapsed = time.time() - start_time
    print(f"\n--- Completato in {elapsed:.2f} s ---")

if __name__ == "__main__":
    # Serve su Windows per far funzionare correttamente il calcolo parallelo.
    multiprocessing.freeze_support() 
    main()