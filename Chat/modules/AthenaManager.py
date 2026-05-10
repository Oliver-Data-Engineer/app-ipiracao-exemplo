import boto3
import time
import copy
from typing import Optional, Dict, List, Any
from .AwsConn import AWSClient
from .GenericLogger import GenericLogger



class AthenaManager(AWSClient):
    """
    Classe responsável por orquestrar execuções no Amazon Athena.
    Gerencia consultas assíncronas, operações de UNLOAD e CTAS com medição de performance.
    """

    def __init__(self, region_name: str = "us-east-2",logger_name = 'YGGDRA'):
        super().__init__(service_name="athena", region_name=region_name)
        self.region_name = region_name
        self.logger = GenericLogger(name=f'{logger_name}.Glue', propagate=True)
        self.logger.info(f"AthenaManager inicializado na região: {self.region_name}")

    # --- MÉTODOS PRIVADOS DE SUPORTE ---

    def _wait_for_query(self, query_id: str, timeout: int = 300) -> str:
        """Aguarda a conclusão da query com polling baseado na resposta do Athena."""

        start = time.time()

        while True:
            response = self.client.get_query_execution(QueryExecutionId=query_id)
            status = response["QueryExecution"]["Status"]["State"]

            if status == "SUCCEEDED":
                elapsed = time.time() - start
                self.logger.info(f"Query {query_id} finalizada em {elapsed:.1f}s.")
                return status

            if status in ["FAILED", "CANCELLED"]:
                elapsed = time.time() - start
                reason = response["QueryExecution"]["Status"].get("StateChangeReason", "Sem motivo informado.")
                self.logger.error(f"Query {query_id} encerrou com {status} após {elapsed:.1f}s: {reason}")
                return status

            if time.time() - start >= timeout:
                raise TimeoutError(f"A query {query_id} excedeu o limite de {timeout}s.")

            time.sleep(5)

    # --- EXECUÇÃO DE QUERIES (DML / DDL) ---

    def execute_query(self, sql: str, database: str, output_s3: str, workgroup: str = "primary") -> Dict:
        """Executa uma query e retorna um dicionário com ID, status, motivo e tempo decorrido."""
        
        clean_output = output_s3 if output_s3.startswith("s3://") else f"s3://{output_s3}"
        
        try:
            resp = self.client.start_query_execution(
                QueryString=sql,
                QueryExecutionContext={"Database": database},
                ResultConfiguration={"OutputLocation": clean_output},
                WorkGroup=workgroup
            )
            query_id = resp["QueryExecutionId"]
            
            # Aguarda a query sair dos estados de processamento (QUEUED / RUNNING)
            self._wait_for_query(query_id)

            # Busca o status oficial de finalização diretamente do Athena
            exec_info = self.client.get_query_execution(QueryExecutionId=query_id)
            status_info = exec_info['QueryExecution']['Status']
            
            final_status = status_info['State'] # Retorna SUCCEEDED, FAILED ou CANCELLED
            motivo = status_info.get('StateChangeReason', '') # Captura a mensagem de erro, se houver

            return {
                "status": final_status,
                "reason": motivo,
                "query_id": query_id
            }

        except Exception as e:
            self.logger.error(f"Erro ao disparar/aguardar query no Athena após ")
            raise

    # --- MÉTODOS DE UTILITÁRIOS ---

    def _extract_bucket(self, s3_uri: str) -> str:
        return s3_uri.replace("s3://", "").split("/")[0]

    def _extract_prefix(self, s3_uri: str) -> str:
        parts = s3_uri.replace("s3://", "").split("/", 1)
        return parts[1] if len(parts) > 1 else ""

    @property
    def _glue(self):
        if not hasattr(self, '_glue_client'):
            self._glue_client = self.session.client('glue', region_name=self.region)
        return self._glue_client

    # --- CATÁLOGO (Glue API) ---

    def list_databases(self) -> List[str]:
        """Lista todos os databases disponíveis no Glue Catalog."""
        start = time.time()
        databases = []
        try:
            paginator = self._glue.get_paginator('get_databases')
            for page in paginator.paginate():
                for db in page.get('DatabaseList', []):
                    databases.append(db['Name'])
            self.logger.info(f"{len(databases)} databases listados em {time.time() - start:.1f}s.")
            return databases
        except Exception as e:
            self.logger.error(f"Erro ao listar databases: {e}")
            raise

    def list_tables(self, db: str) -> Dict[str, Dict[str, str]]:
        """Lista todas as tabelas de um database indexadas pelo nome da tabela."""
        start = time.time()
        tables = {}
        try:
            paginator = self._glue.get_paginator('get_tables')
            for page in paginator.paginate(DatabaseName=db):
                for table in page.get('TableList', []):
                    name = table['Name']
                    tables[name] = {"database": db, "table": name}
            self.logger.info(f"{len(tables)} tabelas listadas em {db} em {time.time() - start:.1f}s.")
            return tables
        except Exception as e:
            self.logger.error(f"Erro ao listar tabelas de {db}: {e}")
            raise

    def get_table_ddl_full(self, db: str, table: str) -> Dict[str, Any]:
        """Retorna DDL completo com comentários de colunas e partições via Glue Catalog."""
        start = time.time()

        def _build_col_line(col: Dict) -> str:
            line = f"`{col['name']}` {col['type']}"
            if col['comment']:
                line += f" COMMENT '{col['comment'].replace(chr(39), chr(92) + chr(39))}'"
            return line

        try:
            response = self._glue.get_table(DatabaseName=db, Name=table)
            table_data = response['Table']
            storage = table_data.get('StorageDescriptor', {})

            columns = [
                {"name": c['Name'], "type": c['Type'], "comment": c.get('Comment', '')}
                for c in storage.get('Columns', [])
            ]
            partition_keys = [
                {"name": p['Name'], "type": p['Type'], "comment": p.get('Comment', '')}
                for p in table_data.get('PartitionKeys', [])
            ]

            ddl = f"CREATE EXTERNAL TABLE `{db}`.`{table}` (\n    "
            ddl += ",\n    ".join(_build_col_line(c) for c in columns)
            ddl += "\n)\n"

            if partition_keys:
                ddl += "PARTITIONED BY (\n    "
                ddl += ",\n    ".join(_build_col_line(p) for p in partition_keys)
                ddl += "\n)\n"

            serde = storage.get('SerdeInfo', {})
            if serde.get('SerializationLibrary'):
                ddl += f"ROW FORMAT SERDE '{serde['SerializationLibrary']}'\n"
            if storage.get('InputFormat'):
                ddl += f"STORED AS INPUTFORMAT '{storage['InputFormat']}'\n"
            if storage.get('OutputFormat'):
                ddl += f"OUTPUTFORMAT '{storage['OutputFormat']}'\n"
            if storage.get('Location'):
                ddl += f"LOCATION '{storage['Location']}'\n"

            self.logger.info(f"DDL de {db}.{table} obtido em {time.time() - start:.1f}s.")
            return {
                "database": db,
                "table": table,
                "location": storage.get('Location'),
                "columns": columns,
                "partition_keys": partition_keys,
                "parameters": table_data.get('Parameters', {}),
                "serde": {
                    "serialization_library": serde.get('SerializationLibrary'),
                    "parameters": serde.get('Parameters', {})
                },
                "formats": {
                    "input_format": storage.get('InputFormat'),
                    "output_format": storage.get('OutputFormat')
                },
                "ddl": ddl
            }
        except Exception as e:
            self.logger.error(f"Erro ao obter DDL de {db}.{table}: {e}")
            raise

    def get_table_ddl(self, database: str, table: str, temp_s3: str) -> Dict[str, Any]:
        """
        Extrai o DDL (CREATE TABLE statement) de uma tabela existente no Athena.
        Útil para persistência de metadados e linhagem no YGGDRA.
        """

        
        query_sql = f"SHOW CREATE TABLE {database}.{table}"
        self.logger.info(f"Extraindo DDL da tabela {database}.{table}")

        try:
            # 1. Executa a query usando o motor padronizado da classe
            # Isso já garante o wait_for_query e o registro do tempo
            exec_resp = self.execute_query(query_sql, database, temp_s3)
            query_id = exec_resp["query_id"]

            # 2. Coleta os resultados da execução
            results = self.client.get_query_results(QueryExecutionId=query_id)
            
            # 3. Processa as linhas do Athena (o DDL vem fragmentado em linhas)
            # Cada linha do 'SHOW CREATE TABLE' vem como uma VarCharValue única
            ddl_lines = [
                row['Data'][0].get('VarCharValue', '') 
                for row in results['ResultSet']['Rows']
            ]
            ddl_final = "\n".join(ddl_lines)

            

            return {
                "status": "Success",
                "database": database,
                "table": table,
                "ddl": ddl_final,
                "query_id": query_id
            }

        except Exception as e:
            self.logger.error(f"Falha ao extrair DDL de {database}.{table}: {str(e)}")
            raise

    def obter_ddl_tabela_athena(database: str, tabela: str, workgroup: str = 'primary') -> str:
        """
        Executa SHOW CREATE TABLE no Athena e retorna o DDL como string.
        """
        client = boto3.client('athena')
        query = f"SHOW CREATE TABLE {database}.{tabela}"

        # 1. Inicia a execução da query
        try:
            start_response = client.start_query_execution(
                QueryString=query,
                WorkGroup=workgroup
                # Se não usar Workgroup configurado com bucket de output, 
                # adicione: ResultConfiguration={'OutputLocation': 's3://seu-bucket-de-logs/'}
            )
            query_execution_id = start_response['QueryExecutionId']
        except Exception as e:
            raise RuntimeError(f"Erro ao iniciar a query no Athena: {e}")

        # 2. Loop de espera (Polling) para a query finalizar
        while True:
            status_response = client.get_query_execution(QueryExecutionId=query_execution_id)
            status = status_response['QueryExecution']['Status']['State']

            if status == 'SUCCEEDED':
                break
            elif status in ['FAILED', 'CANCELLED']:
                reason = status_response['QueryExecution']['Status'].get('StateChangeReason', 'Motivo desconhecido')
                raise RuntimeError(f"A query falhou com status {status}. Motivo: {reason}")
            
            # Aguarda 1 segundo antes de checar novamente para não estourar o limite da API
            time.sleep(1)

        # 3. Busca os resultados da query
        results_response = client.get_query_results(QueryExecutionId=query_execution_id)

        # 4. Processa o JSON para extrair o texto do DDL
        linhas_ddl = []
        
        # O Athena retorna os dados dentro de ['ResultSet']['Rows']
        for row in results_response['ResultSet']['Rows']:
            # Cada linha tem um array 'Data'. Pegamos a primeira coluna [0].
            # Usamos .get('VarCharValue') para evitar erros caso a linha venha vazia
            valor_coluna = row['Data'][0].get('VarCharValue', '')
            
            # O Athena costuma retornar o nome da coluna ('createtab_stmt') na primeira linha. 
            # Ignoramos essa linha de cabeçalho.
            if valor_coluna and valor_coluna != 'createtab_stmt':
                linhas_ddl.append(valor_coluna)

        # 5. Junta todas as linhas com quebra de linha para formar a string final
        ddl_completo = '\n'.join(linhas_ddl)
        
        return ddl_completo
    
    def validate_query(self, sql: str, database: str, temp_s3: str) -> Dict[str, Any]:
        """
        Executa um EXPLAIN na query para validar sintaxe, semântica e existência
        das tabelas/colunas subjacentes sem processar os dados reais.
        
        Padrão 'Fail Fast' para evitar custos no Athena.
        
        :param sql: A query SQL original que será testada.
        :param database: O banco de dados de contexto.
        :param temp_s3: Caminho S3 para o output temporário do Athena.
        :return: Dicionário contendo o status de validação e a mensagem de erro (se houver).
        """
        self.logger.info("🧪 Validando a estrutura da query no Athena (EXPLAIN)...")
        
        # 1. Limpeza preventiva: Removemos espaços e o ';' final para não quebrar o EXPLAIN
        clean_sql = sql.strip().rstrip(';')
        
        # 2. Monta a query de validação
        explain_sql = f"EXPLAIN {clean_sql};"
        
        try:
            # 3. Executa a query usando o nosso motor padrão
            resp = self.execute_query(
                sql=explain_sql, 
                database=database, 
                output_s3=temp_s3
            )
            
            self.logger.info("✅ Query validada com sucesso! Estrutura e origens estão corretas.")
            return {
                "is_valid": True,
                "error": None,
                "query_id": resp.get('query_id')
            }

        except Exception as e:
            # O execute_query já lança uma exceção se a AWS retornar FAILED.
            error_msg = str(e)
            self.logger.error(f"❌ Falha na validação da Query. O Athena recusou a execução.")
            
            return {
                "is_valid": False,
                "error": error_msg,
                "query_id": None
            }