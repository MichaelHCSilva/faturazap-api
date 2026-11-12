#C:\Users\micha\OneDrive\Documentos\FaturaZap\src\core\reporter.py
import sqlite3
import os

DB_PATH = os.path.join("data", "faturazap.db")

def get_financial_summary():
    """
    Consulta o banco de dados e retorna um resumo consolidado 
    dos gastos por cartão/origem e o total geral acumulado.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Busca o total de gastos agrupado por cartão/origem
        cursor.execute('''
            SELECT c.name as card_name,
                   SUM(s.total_amount) as total_spent,
                   COUNT(s.id) as statements_count
            FROM statements s
            JOIN cards c ON s.card_id = c.id
            GROUP BY c.name
        ''')
        results = cursor.fetchall()
        conn.close()

        if not results:
            return "📊 Você ainda não possui faturas ou cupons processados no FaturaZap."

        report = "📊 *Resumo Financeiro FaturaZap*\n\n"
        general_total = 0.0

        for row in results:
            card_name, total_spent, count = row
            safe_total = total_spent if total_spent else 0.0
            general_total += safe_total
            report += f"💳 *{card_name}* ({count} documento(s))\n"
            report += f"   Total: R$ {safe_total:.2f}\n\n"

        report += f"💰 *Gasto Total Acumulado:* R$ {general_total:.2f}"
        return report

    except Exception as e:
        return f"❌ Erro ao gerar o relatório financeiro: {e}"

if __name__ == "__main__":
    print(get_financial_summary())