"""
Final Ingestion Script for Hybrid GraphRAG System
Nạp dữ liệu vào Neo4j (Graph) và ChromaDB (Vector) cho Digital Twin Agent

Features:
- PhoBERT embeddings cho ChromaDB
- Graph schema với TASK dimensions cho Neo4j
- Cross-reference via neo4j_id
- Citation support với raw text của T-A-S-K
"""

import json
import uuid
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# LIBRARY IMPORTS
# ============================================================================

# Neo4j
try:
    from neo4j import GraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    print("Warning: neo4j not installed. Run: pip install neo4j")

# ChromaDB
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("Warning: chromadb not installed. Run: pip install chromadb")

# PhoBERT
try:
    import torch
    from transformers import AutoModel, AutoTokenizer
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    print("Warning: transformers not installed. Run: pip install transformers torch")

# PyVi
try:
    from pyvi import ViTokenizer
    PYVI_AVAILABLE = True
except ImportError:
    PYVI_AVAILABLE = False
    print("Warning: pyvi not installed. Run: pip install pyvi")


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Configuration for ingestion."""
    # Neo4j
    NEO4J_URI = "bolt://127.0.0.1:7687"
    NEO4J_USER = "neo4j"
    NEO4J_PASSWORD = "password123"
    
    # ChromaDB
    CHROMADB_HOST = "localhost"
    CHROMADB_PORT = 8000
    CHROMADB_COLLECTION = "nova_digital_twin_v2"
    
    # PhoBERT
    PHOBERT_MODEL = "vinai/phobert-base-v2"
    
    # Batch sizes
    NEO4J_BATCH_SIZE = 100
    CHROMADB_BATCH_SIZE = 50


# ============================================================================
# PHOBERT EMBEDDER
# ============================================================================

class PhoBERTEmbedder:
    """PhoBERT-based text embedder optimized for Vietnamese."""
    
    def __init__(self, model_name: str = Config.PHOBERT_MODEL):
        if not TRANSFORMERS_AVAILABLE:
            raise ImportError("transformers and torch are required")
        
        print(f"   Loading PhoBERT: {model_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name)
        self.model.eval()
        
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model.to(self.device)
        print(f"   Model loaded on: {self.device}")
    
    def preprocess(self, text: str) -> str:
        """Preprocess text with Vietnamese tokenization."""
        if not text:
            return ""
        text = text.strip()
        if PYVI_AVAILABLE:
            text = ViTokenizer.tokenize(text)
        return text
    
    def embed(self, text: str) -> List[float]:
        """Generate embedding for text."""
        if not text or not text.strip():
            return [0.0] * 768
        
        processed = self.preprocess(text)
        
        inputs = self.tokenizer(
            processed,
            return_tensors='pt',
            max_length=256,
            truncation=True,
            padding=True
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            embedding = outputs.last_hidden_state[:, 0, :].cpu().numpy()
        
        return embedding.flatten().tolist()
    
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        return [self.embed(text) for text in texts]


# ============================================================================
# NEO4J GRAPH MANAGER
# ============================================================================

class Neo4jManager:
    """Neo4j graph database manager."""
    
    def __init__(self, uri: str = Config.NEO4J_URI,
                 user: str = Config.NEO4J_USER,
                 password: str = Config.NEO4J_PASSWORD):
        if not NEO4J_AVAILABLE:
            raise ImportError("neo4j driver is required")
        
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._verify_connection()
    
    def _verify_connection(self):
        """Verify Neo4j connection."""
        with self.driver.session() as session:
            result = session.run("RETURN 1 AS test")
            result.single()
        print("   ✓ Neo4j connection verified")
    
    def close(self):
        """Close driver connection."""
        self.driver.close()
    
    def clear_database(self):
        """Clear all nodes and relationships."""
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        print("   ✓ Database cleared")
    
    def create_constraints(self):
        """Create uniqueness constraints and indexes."""
        constraints = [
            "CREATE CONSTRAINT emp_id IF NOT EXISTS FOR (e:Employee) REQUIRE e.employee_id IS UNIQUE",
            "CREATE CONSTRAINT pos_name IF NOT EXISTS FOR (p:Position) REQUIRE p.name IS UNIQUE",
            "CREATE CONSTRAINT dept_name IF NOT EXISTS FOR (d:Department) REQUIRE d.name IS UNIQUE",
            "CREATE INDEX emp_name IF NOT EXISTS FOR (e:Employee) ON (e.name)",
            "CREATE INDEX emp_neo4j_id IF NOT EXISTS FOR (e:Employee) ON (e.neo4j_id)",
        ]
        
        with self.driver.session() as session:
            for constraint in constraints:
                try:
                    session.run(constraint)
                except Exception as e:
                    # Constraint may already exist
                    pass
        print("   ✓ Constraints and indexes created")
    
    def create_employee_node(self, employee: Dict[str, Any]) -> str:
        """
        Create Employee node with all properties.
        Returns the neo4j element ID.
        """
        query = """
        CREATE (e:Employee {
            employee_id: $employee_id,
            neo4j_id: $neo4j_id,
            name: $name,
            email: $email,
            phone: $phone,
            birth_date: $birth_date,
            experience_years: $experience_years,
            source_file: $source_file,
            created_at: $created_at
        })
        RETURN elementId(e) AS neo4j_id
        """
        
        basic = employee.get('basic_info', {})
        neo4j_id = f"neo4j_{employee.get('employee_id', uuid.uuid4().hex[:8])}"
        
        params = {
            'employee_id': employee.get('employee_id'),
            'neo4j_id': neo4j_id,
            'name': basic.get('full_name', 'Unknown'),
            'email': basic.get('email'),
            'phone': basic.get('phone'),
            'birth_date': basic.get('birth_date'),
            'experience_years': basic.get('experience_years', 0),
            'source_file': employee.get('source_file'),
            'created_at': datetime.now().isoformat(),
        }
        
        with self.driver.session() as session:
            result = session.run(query, params)
            record = result.single()
            return neo4j_id
    
    def create_position_relationship(self, neo4j_id: str, position: str):
        """Create Position node and HAS_POSITION relationship."""
        if not position:
            return
        
        query = """
        MATCH (e:Employee {neo4j_id: $neo4j_id})
        MERGE (p:Position {name: $position})
        MERGE (e)-[:HAS_POSITION]->(p)
        """
        
        with self.driver.session() as session:
            session.run(query, {'neo4j_id': neo4j_id, 'position': position})
    
    def create_department_relationship(self, neo4j_id: str, department: str):
        """Create Department node and WORKS_IN relationship."""
        if not department:
            return
        
        query = """
        MATCH (e:Employee {neo4j_id: $neo4j_id})
        MERGE (d:Department {name: $department})
        MERGE (e)-[:WORKS_IN]->(d)
        """
        
        with self.driver.session() as session:
            session.run(query, {'neo4j_id': neo4j_id, 'department': department})
    
    def create_task_nodes(self, neo4j_id: str, task_profile: Dict[str, Any]):
        """Create TASK dimension nodes and relationships."""
        task_types = {
            'thinking': ('Thinking', 'HAS_THINKING'),
            'attitude': ('Attitude', 'HAS_ATTITUDE'),
            'skill': ('Skill', 'HAS_SKILL'),
            'knowledge': ('Knowledge', 'HAS_KNOWLEDGE'),
        }
        
        for task_key, (label, rel_type) in task_types.items():
            task_data = task_profile.get(task_key, {})
            content = task_data.get('content', '')
            keywords = task_data.get('keywords', [])
            
            if not content:
                continue
            
            query = f"""
            MATCH (e:Employee {{neo4j_id: $neo4j_id}})
            CREATE (t:{label} {{
                content: $content,
                keywords: $keywords,
                description: $description,
                employee_id: e.employee_id
            }})
            CREATE (e)-[:{rel_type}]->(t)
            """
            
            params = {
                'neo4j_id': neo4j_id,
                'content': content[:2000],  # Truncate for Neo4j
                'keywords': keywords,
                'description': task_data.get('description', ''),
            }
            
            with self.driver.session() as session:
                session.run(query, params)
    
    def create_skill_connections(self):
        """Create SHARES_SKILL relationships between employees with common skills."""
        query = """
        MATCH (e1:Employee)-[:HAS_SKILL]->(s1:Skill)
        MATCH (e2:Employee)-[:HAS_SKILL]->(s2:Skill)
        WHERE e1 <> e2
        AND ANY(k IN s1.keywords WHERE k IN s2.keywords)
        WITH e1, e2, 
             [k IN s1.keywords WHERE k IN s2.keywords] AS shared_skills
        WHERE size(shared_skills) >= 2
        MERGE (e1)-[r:SHARES_SKILLS_WITH]-(e2)
        ON CREATE SET r.shared_skills = shared_skills, r.count = size(shared_skills)
        """
        
        with self.driver.session() as session:
            session.run(query)
        print("   ✓ Skill connections created")
    
    def get_statistics(self) -> Dict[str, int]:
        """Get database statistics."""
        stats = {}
        
        queries = {
            'employees': "MATCH (e:Employee) RETURN count(e) AS count",
            'positions': "MATCH (p:Position) RETURN count(p) AS count",
            'departments': "MATCH (d:Department) RETURN count(d) AS count",
            'thinking_nodes': "MATCH (t:Thinking) RETURN count(t) AS count",
            'attitude_nodes': "MATCH (a:Attitude) RETURN count(a) AS count",
            'skill_nodes': "MATCH (s:Skill) RETURN count(s) AS count",
            'knowledge_nodes': "MATCH (k:Knowledge) RETURN count(k) AS count",
            'relationships': "MATCH ()-[r]->() RETURN count(r) AS count",
        }
        
        with self.driver.session() as session:
            for key, query in queries.items():
                result = session.run(query)
                record = result.single()
                stats[key] = record['count'] if record else 0
        
        return stats


# ============================================================================
# CHROMADB VECTOR MANAGER
# ============================================================================

class ChromaDBManager:
    """ChromaDB vector database manager."""
    
    def __init__(self, host: str = Config.CHROMADB_HOST,
                 port: int = Config.CHROMADB_PORT,
                 collection_name: str = Config.CHROMADB_COLLECTION):
        if not CHROMADB_AVAILABLE:
            raise ImportError("chromadb is required")
        
        self.client = chromadb.HttpClient(host=host, port=port)
        self.collection_name = collection_name
        self.collection = None
        self._verify_connection()
    
    def _verify_connection(self):
        """Verify ChromaDB connection."""
        heartbeat = self.client.heartbeat()
        print(f"   ✓ ChromaDB connection verified (heartbeat: {heartbeat})")
    
    def create_collection(self, delete_existing: bool = True):
        """Create or get collection."""
        if delete_existing:
            try:
                self.client.delete_collection(name=self.collection_name)
                print(f"   ✓ Deleted existing collection: {self.collection_name}")
            except:
                pass
        
        self.collection = self.client.create_collection(
            name=self.collection_name,
            metadata={
                "description": "NovaTech Digital Twin Employee Vectors",
                "model": Config.PHOBERT_MODEL,
                "created_at": datetime.now().isoformat(),
                "hnsw:space": "cosine"
            }
        )
        print(f"   ✓ Created collection: {self.collection_name}")
    
    def add_employee(self, employee: Dict[str, Any], 
                     neo4j_id: str,
                     embedding: List[float]):
        """Add single employee to collection."""
        basic = employee.get('basic_info', {})
        task = employee.get('task_profile', {})
        
        # Build metadata with TASK content for citations
        metadata = {
            # Core IDs (for cross-reference)
            'neo4j_id': neo4j_id,
            'employee_id': employee.get('employee_id', ''),
            
            # Basic info
            'name': basic.get('full_name', 'Unknown'),
            'position': basic.get('position') or '',
            'department': basic.get('department') or '',
            'email': basic.get('email') or '',
            'phone': basic.get('phone') or '',
            'experience_years': basic.get('experience_years', 0),
            'source_file': employee.get('source_file', ''),
            
            # TASK raw content for Agent citations
            'task_thinking': (task.get('thinking', {}).get('content', '') or '')[:500],
            'task_attitude': (task.get('attitude', {}).get('content', '') or '')[:500],
            'task_skill': (task.get('skill', {}).get('content', '') or '')[:500],
            'task_knowledge': (task.get('knowledge', {}).get('content', '') or '')[:500],
            
            # Keywords as comma-separated string
            'skill_keywords': ','.join(task.get('skill', {}).get('keywords', [])),
        }
        
        # Document text (for search)
        document = employee.get('embedding_text', '') or employee.get('cleaned_text', '')
        
        self.collection.add(
            ids=[neo4j_id],
            embeddings=[embedding],
            metadatas=[metadata],
            documents=[document[:5000]]  # Truncate document
        )
    
    def add_batch(self, employees: List[Dict[str, Any]],
                  neo4j_ids: List[str],
                  embeddings: List[List[float]]):
        """Add batch of employees to collection."""
        ids = []
        all_embeddings = []
        metadatas = []
        documents = []
        
        for emp, neo4j_id, emb in zip(employees, neo4j_ids, embeddings):
            basic = emp.get('basic_info', {})
            task = emp.get('task_profile', {})
            
            metadata = {
                'neo4j_id': neo4j_id,
                'employee_id': emp.get('employee_id', ''),
                'name': basic.get('full_name', 'Unknown'),
                'position': basic.get('position') or '',
                'department': basic.get('department') or '',
                'email': basic.get('email') or '',
                'phone': basic.get('phone') or '',
                'experience_years': basic.get('experience_years', 0),
                'source_file': emp.get('source_file', ''),
                'task_thinking': (task.get('thinking', {}).get('content', '') or '')[:500],
                'task_attitude': (task.get('attitude', {}).get('content', '') or '')[:500],
                'task_skill': (task.get('skill', {}).get('content', '') or '')[:500],
                'task_knowledge': (task.get('knowledge', {}).get('content', '') or '')[:500],
                'skill_keywords': ','.join(task.get('skill', {}).get('keywords', [])),
            }
            
            doc = emp.get('embedding_text', '') or emp.get('cleaned_text', '')
            
            ids.append(neo4j_id)
            all_embeddings.append(emb)
            metadatas.append(metadata)
            documents.append(doc[:5000])
        
        self.collection.add(
            ids=ids,
            embeddings=all_embeddings,
            metadatas=metadatas,
            documents=documents
        )
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get collection statistics."""
        if not self.collection:
            return {}
        
        return {
            'name': self.collection_name,
            'count': self.collection.count(),
        }
    
    def verify_cross_reference(self, neo4j_ids: List[str]) -> Tuple[int, int]:
        """Verify all neo4j_ids exist in ChromaDB."""
        results = self.collection.get(ids=neo4j_ids)
        found = len(results['ids'])
        total = len(neo4j_ids)
        return found, total


# ============================================================================
# INGESTION PIPELINE
# ============================================================================

class IngestionPipeline:
    """Main ingestion pipeline for Hybrid GraphRAG."""
    
    def __init__(self):
        self.embedder = None
        self.neo4j = None
        self.chromadb = None
        self.neo4j_ids = []
    
    def initialize(self):
        """Initialize all components."""
        print("\n🔧 Initializing components...")
        
        # PhoBERT Embedder
        print("\n   [1/3] PhoBERT Embedder")
        self.embedder = PhoBERTEmbedder()
        
        # Neo4j
        print("\n   [2/3] Neo4j Connection")
        self.neo4j = Neo4jManager()
        
        # ChromaDB
        print("\n   [3/3] ChromaDB Connection")
        self.chromadb = ChromaDBManager()
        
        print("\n   ✓ All components initialized")
    
    def prepare_databases(self):
        """Prepare databases for ingestion."""
        print("\n🗑️  Preparing databases...")
        
        # Clear and setup Neo4j
        self.neo4j.clear_database()
        self.neo4j.create_constraints()
        
        # Create ChromaDB collection
        self.chromadb.create_collection(delete_existing=True)
        
        print("   ✓ Databases prepared")
    
    def ingest_to_neo4j(self, employees: List[Dict[str, Any]]) -> List[str]:
        """
        Ingest all employees to Neo4j.
        Returns list of neo4j_ids.
        """
        print(f"\n📊 Ingesting to Neo4j ({len(employees)} employees)...")
        
        neo4j_ids = []
        
        for i, emp in enumerate(employees):
            # Create employee node
            neo4j_id = self.neo4j.create_employee_node(emp)
            neo4j_ids.append(neo4j_id)
            
            basic = emp.get('basic_info', {})
            task = emp.get('task_profile', {})
            
            # Create relationships
            self.neo4j.create_position_relationship(neo4j_id, basic.get('position'))
            self.neo4j.create_department_relationship(neo4j_id, basic.get('department'))
            
            # Create TASK dimension nodes
            self.neo4j.create_task_nodes(neo4j_id, task)
            
            if (i + 1) % 20 == 0:
                print(f"   Processed {i + 1}/{len(employees)} employees...")
        
        # Create skill-based connections
        self.neo4j.create_skill_connections()
        
        print(f"   ✓ Neo4j ingestion complete")
        return neo4j_ids
    
    def ingest_to_chromadb(self, employees: List[Dict[str, Any]], 
                           neo4j_ids: List[str]):
        """Ingest all employees to ChromaDB with embeddings."""
        print(f"\n🔮 Ingesting to ChromaDB ({len(employees)} employees)...")
        
        batch_size = Config.CHROMADB_BATCH_SIZE
        
        for i in range(0, len(employees), batch_size):
            batch_emp = employees[i:i + batch_size]
            batch_ids = neo4j_ids[i:i + batch_size]
            
            # Generate embeddings
            texts = [emp.get('embedding_text', '') or emp.get('cleaned_text', '') 
                     for emp in batch_emp]
            embeddings = self.embedder.embed_batch(texts)
            
            # Add to ChromaDB
            self.chromadb.add_batch(batch_emp, batch_ids, embeddings)
            
            print(f"   Processed {min(i + batch_size, len(employees))}/{len(employees)} employees...")
        
        print(f"   ✓ ChromaDB ingestion complete")
    
    def verify_cross_reference(self, neo4j_ids: List[str]):
        """Verify 100% cross-reference between Neo4j and ChromaDB."""
        print("\n🔍 Verifying cross-reference...")
        
        found, total = self.chromadb.verify_cross_reference(neo4j_ids)
        
        if found == total:
            print(f"   ✓ Cross-reference verified: {found}/{total} (100%)")
            return True
        else:
            print(f"   ⚠️ Cross-reference mismatch: {found}/{total} ({found/total*100:.1f}%)")
            return False
    
    def print_statistics(self):
        """Print final statistics."""
        print("\n" + "=" * 60)
        print("  INGESTION STATISTICS")
        print("=" * 60)
        
        # Neo4j stats
        neo4j_stats = self.neo4j.get_statistics()
        print("\n  📊 Neo4j Graph Database:")
        print(f"     Employees:     {neo4j_stats.get('employees', 0)}")
        print(f"     Positions:     {neo4j_stats.get('positions', 0)}")
        print(f"     Departments:   {neo4j_stats.get('departments', 0)}")
        print(f"     Thinking:      {neo4j_stats.get('thinking_nodes', 0)}")
        print(f"     Attitude:      {neo4j_stats.get('attitude_nodes', 0)}")
        print(f"     Skill:         {neo4j_stats.get('skill_nodes', 0)}")
        print(f"     Knowledge:     {neo4j_stats.get('knowledge_nodes', 0)}")
        print(f"     Relationships: {neo4j_stats.get('relationships', 0)}")
        
        # ChromaDB stats
        chroma_stats = self.chromadb.get_statistics()
        print("\n  🔮 ChromaDB Vector Database:")
        print(f"     Collection:    {chroma_stats.get('name', 'N/A')}")
        print(f"     Vectors:       {chroma_stats.get('count', 0)}")
        print(f"     Model:         {Config.PHOBERT_MODEL}")
        
        print("\n" + "=" * 60)
    
    def close(self):
        """Close all connections."""
        if self.neo4j:
            self.neo4j.close()
        print("\n✓ Connections closed")
    
    def run(self, input_file: str):
        """Run full ingestion pipeline."""
        print("\n" + "=" * 60)
        print("  HYBRID GRAPHRAG INGESTION PIPELINE")
        print("  Neo4j v5.26.0 + ChromaDB + PhoBERT")
        print("=" * 60)
        
        # Load data
        print(f"\n📂 Loading data from: {input_file}")
        employees = load_data(input_file)
        print(f"   Loaded {len(employees)} employees")
        
        # Initialize
        self.initialize()
        
        # Prepare databases
        self.prepare_databases()
        
        # Ingest to Neo4j
        neo4j_ids = self.ingest_to_neo4j(employees)
        self.neo4j_ids = neo4j_ids
        
        # Ingest to ChromaDB
        self.ingest_to_chromadb(employees, neo4j_ids)
        
        # Verify cross-reference
        cross_ref_ok = self.verify_cross_reference(neo4j_ids)
        
        # Print statistics
        self.print_statistics()
        
        # Conclusion
        print("\n" + "=" * 60)
        print("  CONCLUSION")
        print("=" * 60)
        
        if cross_ref_ok:
            print("\n  ✅ INGESTION SUCCESSFUL")
            print("\n  ➤ Tất cả dữ liệu đã được nạp thành công.")
            print("  ➤ Neo4j: Graph structure với TASK dimensions.")
            print("  ➤ ChromaDB: PhoBERT embeddings với citations metadata.")
            print("  ➤ Cross-reference: 100% neo4j_id mapping.")
            print("\n  🎯 Hybrid GraphRAG ready for Digital Twin Agent!")
        else:
            print("\n  ⚠️ INGESTION COMPLETED WITH WARNINGS")
            print("\n  ➤ Some cross-reference mismatches detected.")
            print("  ➤ Please verify data integrity.")
        
        print("\n" + "=" * 60)
        
        # Close connections
        self.close()
        
        return cross_ref_ok


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def load_data(file_path: str) -> List[Dict[str, Any]]:
    """Load employee data from JSON file."""
    path = Path(file_path)
    
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if isinstance(data, dict) and 'employees' in data:
        return data['employees']
    elif isinstance(data, list):
        return data
    else:
        raise ValueError("Invalid data format")


def test_queries():
    """Run test queries to verify ingestion."""
    print("\n🧪 Running test queries...")
    
    # Test Neo4j
    if NEO4J_AVAILABLE:
        driver = GraphDatabase.driver(
            Config.NEO4J_URI,
            auth=(Config.NEO4J_USER, Config.NEO4J_PASSWORD)
        )
        
        with driver.session() as session:
            # Query 1: Get employee with skills
            result = session.run("""
                MATCH (e:Employee)-[:HAS_SKILL]->(s:Skill)
                RETURN e.name AS name, e.neo4j_id AS neo4j_id, s.keywords AS skills
                LIMIT 3
            """)
            
            print("\n   Neo4j Sample Query (Employees with Skills):")
            for record in result:
                print(f"   - {record['name']}: {record['skills'][:3]}...")
        
        driver.close()
    
    # Test ChromaDB
    if CHROMADB_AVAILABLE:
        client = chromadb.HttpClient(
            host=Config.CHROMADB_HOST,
            port=Config.CHROMADB_PORT
        )
        
        collection = client.get_collection(Config.CHROMADB_COLLECTION)
        
        # Query by metadata
        results = collection.get(
            limit=3,
            include=['metadatas']
        )
        
        print("\n   ChromaDB Sample Query (First 3 records):")
        for i, metadata in enumerate(results['metadatas']):
            print(f"   - {metadata['name']} (neo4j_id: {metadata['neo4j_id']})")
    
    print("\n   ✓ Test queries completed")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Ingest data into Hybrid GraphRAG (Neo4j + ChromaDB)'
    )
    parser.add_argument('--input', '-i', type=str, default='clean_data.json',
                        help='Input JSON file (default: clean_data.json)')
    parser.add_argument('--test', '-t', action='store_true',
                        help='Run test queries after ingestion')
    parser.add_argument('--neo4j-uri', type=str, default=Config.NEO4J_URI,
                        help=f'Neo4j URI (default: {Config.NEO4J_URI})')
    parser.add_argument('--chromadb-host', type=str, default=Config.CHROMADB_HOST,
                        help=f'ChromaDB host (default: {Config.CHROMADB_HOST})')
    parser.add_argument('--chromadb-port', type=int, default=Config.CHROMADB_PORT,
                        help=f'ChromaDB port (default: {Config.CHROMADB_PORT})')
    parser.add_argument('--collection', type=str, default=Config.CHROMADB_COLLECTION,
                        help=f'ChromaDB collection name (default: {Config.CHROMADB_COLLECTION})')
    
    args = parser.parse_args()
    
    # Update config
    Config.NEO4J_URI = args.neo4j_uri
    Config.CHROMADB_HOST = args.chromadb_host
    Config.CHROMADB_PORT = args.chromadb_port
    Config.CHROMADB_COLLECTION = args.collection
    
    # Check dependencies
    missing = []
    if not NEO4J_AVAILABLE:
        missing.append('neo4j')
    if not CHROMADB_AVAILABLE:
        missing.append('chromadb')
    if not TRANSFORMERS_AVAILABLE:
        missing.append('transformers torch')
    
    if missing:
        print(f"\n❌ Missing dependencies: {', '.join(missing)}")
        print(f"   Run: pip install {' '.join(missing)}")
        return
    
    # Run pipeline
    pipeline = IngestionPipeline()
    success = pipeline.run(args.input)
    
    # Run test queries if requested
    if args.test and success:
        test_queries()


if __name__ == "__main__":
    main()
