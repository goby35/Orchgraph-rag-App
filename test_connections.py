"""
Test connections to Neo4j and ChromaDB services
"""

from neo4j import GraphDatabase
import chromadb


def test_neo4j_connection():
    """Test Neo4j connection and print server version"""
    print("=" * 50)
    print("Testing Neo4j Connection...")
    print("=" * 50)
    
    uri = "bolt://localhost:7687"
    username = "neo4j"
    password = "password123"
    
    try:
        driver = GraphDatabase.driver(uri, auth=(username, password))
        
        with driver.session() as session:
            # Get server version
            result = session.run("CALL dbms.components() YIELD name, versions RETURN name, versions")
            for record in result:
                print(f"Component: {record['name']}")
                print(f"Version: {record['versions'][0]}")
            
            # Run simple test query
            result = session.run("RETURN 1 AS test_value")
            record = result.single()
            print(f"\nTest query 'RETURN 1': {record['test_value']}")
            
            # Check APOC plugin
            try:
                result = session.run("RETURN apoc.version() AS apoc_version")
                record = result.single()
                print(f"APOC Version: {record['apoc_version']}")
            except Exception as e:
                print(f"APOC not available: {e}")
            
            # Check GDS plugin
            try:
                result = session.run("RETURN gds.version() AS gds_version")
                record = result.single()
                print(f"GDS Version: {record['gds_version']}")
            except Exception as e:
                print(f"GDS not available: {e}")
        
        driver.close()
        print("\n✓ Neo4j connection successful!")
        return True
        
    except Exception as e:
        print(f"\n✗ Neo4j connection failed: {e}")
        return False


def test_chromadb_connection():
    """Test ChromaDB connection, create collection and add sample data"""
    print("\n" + "=" * 50)
    print("Testing ChromaDB Connection...")
    print("=" * 50)
    
    try:
        # Connect to ChromaDB
        client = chromadb.HttpClient(host="localhost", port=8000)
        
        # Get server heartbeat
        heartbeat = client.heartbeat()
        print(f"ChromaDB Heartbeat: {heartbeat}")
        
        # Get or create collection
        collection_name = "test_nova_tech"
        
        # Delete if exists (for clean test)
        try:
            client.delete_collection(name=collection_name)
            print(f"Deleted existing collection: {collection_name}")
        except:
            pass
        
        # Create new collection
        collection = client.create_collection(
            name=collection_name,
            metadata={"description": "Test collection for GraphRAG project"}
        )
        print(f"\n✓ Created collection: {collection_name}")
        
        # Add sample documents
        sample_documents = [
            "GraphRAG combines knowledge graphs with retrieval-augmented generation.",
            "Neo4j is a popular graph database for storing connected data.",
            "ChromaDB is a vector database optimized for AI applications.",
            "RAG systems enhance LLM responses with external knowledge."
        ]
        
        sample_ids = ["doc1", "doc2", "doc3", "doc4"]
        
        sample_metadata = [
            {"topic": "graphrag", "source": "test"},
            {"topic": "neo4j", "source": "test"},
            {"topic": "chromadb", "source": "test"},
            {"topic": "rag", "source": "test"}
        ]
        
        collection.add(
            documents=sample_documents,
            ids=sample_ids,
            metadatas=sample_metadata
        )
        print(f"✓ Added {len(sample_documents)} sample documents")
        
        # Query the collection
        results = collection.query(
            query_texts=["What is GraphRAG?"],
            n_results=2
        )
        
        print("\nQuery: 'What is GraphRAG?'")
        print("Top 2 results:")
        for i, doc in enumerate(results['documents'][0]):
            print(f"  {i+1}. {doc}")
        
        # Get collection count
        count = collection.count()
        print(f"\nTotal documents in collection: {count}")
        
        print("\n✓ ChromaDB connection successful!")
        return True
        
    except Exception as e:
        print(f"\n✗ ChromaDB connection failed: {e}")
        return False


def main():
    """Run all connection tests"""
    print("\n" + "=" * 50)
    print("  GraphRAG Environment Connection Tests")
    print("=" * 50)
    
    neo4j_ok = test_neo4j_connection()
    chroma_ok = test_chromadb_connection()
    
    print("\n" + "=" * 50)
    print("  Test Summary")
    print("=" * 50)
    print(f"Neo4j:    {'✓ OK' if neo4j_ok else '✗ FAILED'}")
    print(f"ChromaDB: {'✓ OK' if chroma_ok else '✗ FAILED'}")
    
    if neo4j_ok and chroma_ok:
        print("\n🎉 All services are running correctly!")
    else:
        print("\n⚠️  Some services failed. Please check the error messages above.")


if __name__ == "__main__":
    main()
