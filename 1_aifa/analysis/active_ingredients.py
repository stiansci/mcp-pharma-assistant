# analyze_active_ingredients.py

import duckdb
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_NAME = os.path.join(BASE_DIR, '..', 'aifa.db')
    
def analyze_ingredients(db_path):
    """
    Analizza la relazione tra farmaci (AIC) e principi attivi nel database AIFA.
    """
    print(f"--- Inizio Analisi Principi Attivi su '{db_path}' ---")
    
    try:
        con = duckdb.connect(db_path, read_only=True)

        # Query 1: Contare il numero di principi attivi per ogni codice AIC
        # Usiamo GROUP BY e COUNT per aggregare i dati
        query1 = """
        SELECT 
            codice_aic, 
            COUNT(principio_attivo) as num_principi_attivi
        FROM 
            principi_attivi
        WHERE
            principio_attivo IS NOT NULL
        GROUP BY 
            codice_aic
        ORDER BY 
            num_principi_attivi DESC;
        """
        
        print("\n[Analisi 1: Conteggio Principi Attivi per Farmaco (AIC)]")
        df_counts = con.execute(query1).fetchdf()

        # Analisi dei risultati della Query 1
        multi_ingredient_drugs = df_counts[df_counts['num_principi_attivi'] > 1]
        total_drugs_with_ingredients = len(df_counts)
        num_multi_ingredient = len(multi_ingredient_drugs)
        
        if total_drugs_with_ingredients > 0:
            percentage = (num_multi_ingredient / total_drugs_with_ingredients) * 100
            print(f"Totale farmaci con principi attivi specificati: {total_drugs_with_ingredients}")
            print(f"Numero di farmaci con più di un principio attivo: {num_multi_ingredient} ({percentage:.2f}%)")
        
        if not multi_ingredient_drugs.empty:
            max_ingredients = multi_ingredient_drugs['num_principi_attivi'].max()
            print(f"Numero massimo di principi attivi per un singolo farmaco: {max_ingredients}")
            
            print("\nTop 10 farmaci con il maggior numero di principi attivi:")
            print(multi_ingredient_drugs.head(10))

        # Query 3: Analizzare le incongruenze nelle unità di misura
        print("\n[Analisi 3: Incoerenze nelle Unità di Misura]")
        query3 = """
        SELECT 
            principio_attivo, 
            unita_misura, 
            COUNT(*) as conteggio
        FROM 
            principi_attivi
        WHERE 
            principio_attivo IS NOT NULL AND unita_misura IS NOT NULL
        GROUP BY 
            principio_attivo, unita_misura
        HAVING 
            COUNT(*) > 1
        ORDER BY 
            principio_attivo, conteggio DESC;
        """
        df_units = con.execute(query3).fetchdf()
        
        # Troviamo i principi attivi con più di una denominazione per l'unità di misura
        inconsistent_units = df_units.groupby('principio_attivo').filter(lambda x: len(x) > 1)
        
        if inconsistent_units.empty:
            print("Nessuna incoerenza significativa trovata nelle unità di misura.")
        else:
            print("Trovati principi attivi con diverse diciture per le unità di misura (primi 20):")
            print(inconsistent_units.head(20))

    except duckdb.Error as e:
        print(f"Errore durante l'analisi del database: {e}")
    finally:
        if 'con' in locals():
            con.close()
            print("\n--- Analisi completata. Connessione chiusa. ---")

if __name__ == "__main__":
    if not os.path.exists(DATABASE_NAME):
        print(f"Database '{DATABASE_NAME}' non trovato. Esegui prima 'build_aifa_database.py'.")
    else:
        analyze_ingredients(DATABASE_NAME)