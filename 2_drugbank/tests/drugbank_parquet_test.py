
def explore_enriched_data():
    """
    Carica ed esplora i file Parquet arricchiti (inclusi sinonimi e codici ATC)
    e dimostra la loro utilità con query avanzate.
    """
    print("--- Inizio Esplorazione Dati Arricchiti di DrugBank ---")

    required_files = [DRUGS_FILE, SYNONYMS_FILE, ATC_CODES_FILE, AIFA_DB_PATH]
    print("\nControllo dei file necessari:")
    all_found = True
    for f in required_files:
        print(f"Verifica percorso: {f} ... {'TROVATO' if os.path.exists(f) else 'NON TROVATO'}")
        if not os.path.exists(f):
            all_found = False

    if not all_found:
        print("\nErrore: Uno o più file necessari non trovati. Controlla la configurazione dei percorsi all'inizio dello script.")
        return

    # Il resto dello script rimane identico...
    
    # --- Caricamento Dati ---
    print("\n[1. Caricamento e Ispezione dei DataFrame]")
    df_drugs = pl.read_parquet(DRUGS_FILE)
    df_synonyms = pl.read_parquet(SYNONYMS_FILE)
    df_atc = pl.read_parquet(ATC_CODES_FILE)
    
    print(f"Caricati {len(df_drugs):,} farmaci, {len(df_synonyms):,} sinonimi, e {len(df_atc):,} codici ATC.")

    # --- Test 1: Ricerca tramite Sinonimo ---
    print("\n" + "="*70)
    print("[Test 1: Ricerca di un farmaco tramite il suo sinonimo/marchio ('Aspirin')]")
    
    search_term = "Aspirin"
    
    aspirin_synonym = df_synonyms.filter(pl.col('synonym').str.to_lowercase() == search_term.lower())
    
    if aspirin_synonym.is_empty():
        print(f" -> Il sinonimo '{search_term}' non è stato trovato.")
    else:
        aspirin_id = aspirin_synonym['drugbank_id'][0]
        main_drug_record = df_drugs.filter(pl.col('drugbank_id') == aspirin_id)
        if not main_drug_record.is_empty():
            drug_name = main_drug_record['name'][0]
            print(f" -> SUCCESSO: Il sinonimo '{search_term}' (ID: {aspirin_id}) corrisponde al principio attivo: '{drug_name}'")

    # --- Test 2: Collegamento tra AIFA e DrugBank tramite Codice ATC ---
    print("\n" + "="*70)
    print("[Test 2: Join tra dati AIFA e DrugBank usando il Codice ATC]")

    try:
        con = duckdb.connect(AIFA_DB_PATH, read_only=True)
        print(" -> Caricamento dati da aifa.db...")
        aifa_df = con.execute("SELECT DISTINCT codice_atc, denominazione FROM confezioni WHERE codice_atc IS NOT NULL").pl()
        print(f" -> Trovati {len(aifa_df)} record ATC/Denominazione unici in AIFA.")
        
        print(" -> Esecuzione della JOIN tra AIFA e DrugBank...")
        joined_df = df_atc.join(df_drugs, on='drugbank_id').join(aifa_df, left_on='atc_code', right_on='codice_atc')
        
        if joined_df.is_empty():
            print(" -> Nessuna corrispondenza trovata tra i codici ATC di AIFA e DrugBank.")
        else:
            print(f" -> SUCCESSO: Trovate {len(joined_df)} corrispondenze!")
            print("    Mostrando un campione di farmaci presenti in entrambi i database:")
            print(joined_df.sample(5).select([
                pl.col('atc_code'),
                pl.col('denominazione').alias('nome_farmaco_aifa'),
                pl.col('name').alias('principio_attivo_drugbank')
            ]))
    except Exception as e:
        print(f"Errore durante l'interazione con il database AIFA: {e}")
    finally:
        if 'con' in locals():
            con.close()

    print("\n--- Esplorazione dati arricchiti completata. ---")


if __name__ == "__main__":
    explore_enriched_data()