import os
import re
from dotenv import load_dotenv
from groq import Groq

# Carrega a API Key do .env
load_dotenv()

class GroqSkillAgent:
    def __init__(self, skill_file):
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        self.skill_path = skill_file
        self.modelo = "llama-3.3-70b-versatile"

    def _ler_skill(self):
        """Lê o conteúdo bruto do arquivo .skill"""
        with open(self.skill_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _limpar_resposta(self, texto):
        """Garante que retorne apenas o SQL puro, sem markdown"""
        return re.sub(r"```(?:sql)?\n?|```", "", texto).strip()

    def executar(self, pergunta, schema_dinamico):
        """Mapeia o arquivo .skill e envia para o Groq"""
        template = self._ler_skill()
        
        # Injeção dinâmica no template da skill
        prompt_final = template.replace("{{schema}}", schema_dinamico)\
                               .replace("{{pergunta}}", pergunta)

        try:
            completion = self.client.chat.completions.create(
                model=self.modelo,
                messages=[
                    {"role": "system", "content": "Você é um executor de skills técnicas."},
                    {"role": "user", "content": prompt_final}
                ],
                temperature=0.0, # Precisão máxima para SQL
            )
            
            sql_bruto = completion.choices[0].message.content
            return self._limpar_resposta(sql_bruto)
            
        except Exception as e:
            return f"-- Erro na execução da skill: {e}"
