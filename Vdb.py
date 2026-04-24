from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
import json
import threading
import re
from datetime import datetime

# 向量数据库配置
from configs import global_config
INDEX_FILE = "faiss_index.index"
METADATA_FILE = "metadata.jsonl"
EMBEDDING_MODEL = "./LocalLLMs/all-MiniLM-L6-v2"  # 轻量级句子嵌入模型

# 时间匹配正则（精准匹配text首部的[YYYY-MM-DD, HH:MM]）
TIME_PATTERN = r'\[(?P<date>\d{4}-\d{2}-\d{2}), (?P<time>\d{2}:\d{2})\]'

class RAGService:
    def __init__(self, _vdb_path):
        print("ragService_init begin")
        self.vdb_path = _vdb_path
        """初始化RAG服务，加载嵌入模型和向量数据库"""
        self.embedding_model = SentenceTransformer(EMBEDDING_MODEL)
        print("embedding model loaded")
        self.encode_lock = threading.Lock()  # 初始化锁
        self.index = None
        self.metadata = []  # 存储与向量对应的原始文本信息
        self._load_vector_db()
        print("vector database loaded")
        print("ragService_init end")

    def _load_vector_db(self):
        """加载已存在的向量数据库"""
        if not os.path.exists(self.vdb_path):
            print("vdb: No files found.")
            os.makedirs(self.vdb_path)
            # 初始化空索引（384是all-MiniLM-L6-v2的输出维度）
            self.index = faiss.IndexFlatL2(384)
            return

        # 加载索引文件
        index_path = os.path.join(self.vdb_path, INDEX_FILE)
        if os.path.exists(index_path):
            self.index = faiss.read_index(index_path)
        
        # 加载元数据
        metadata_path = os.path.join(self.vdb_path, METADATA_FILE)
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r', encoding='utf-8') as f:
                self.metadata = [json.loads(line) for line in f]

    def _save_vector_db(self):
        """保存向量数据库到磁盘"""
        if self.index is None:
            raise("no index")
            return

        # 保存索引
        index_path = os.path.join(self.vdb_path, INDEX_FILE)
        faiss.write_index(self.index, index_path)

        # 保存元数据
        metadata_path = os.path.join(self.vdb_path, METADATA_FILE)
        with open(metadata_path, 'w', encoding='utf-8') as f:
            for item in self.metadata:
                f.write(json.dumps(item, ensure_ascii=False) + '\n')

    def store(self, texts: list[str], metadatas: list[dict] = None, threshold: float = 0.9) -> bool:
        """
        存储文本到向量数据库
        
        参数:
            texts: 文本列表，如["文本1", "文本2", ...]
            metadatas: 可选，元数据列表，每个元素为字典，如[{"source": "文档1"}, ...]
            threshold: 相似度超过该阈值则拒绝插入
        """
        if not texts:
            return False
        
        # 参数校验：确保texts和metadatas长度一致
        if metadatas is not None and len(texts) != len(metadatas):
            raise ValueError("texts和metadatas长度必须一致")

        # 生成文本嵌入向量（带线程锁）
        with self.encode_lock:
            embeddings = self.embedding_model.encode(texts)
        embeddings = np.array(embeddings).astype('float32')

        # 如果记忆库中已存在和待插入文本的相似度过高的条目，则不进行插入（仅当数据库非空时进行检查）
        filtered_texts = []
        filtered_metadatas = []
        filtered_embeddings = []
        if self.index is not None and self.index.ntotal > 0:
            # 批量搜索所有文本（一次搜索操作）
            distances, indices = self.index.search(embeddings, 1)
            # 检查每个文本的最相似结果
            for i in range(len(texts)):
                # 将L2距离转换为相似度分数（与retrieve保持一致）
                similarity = 1 / (1 + distances[i][0])
                if similarity < threshold:  # 当相似度小于threshold时允许插入
                    filtered_texts.append(texts[i])
                    if metadatas is not None:
                        filtered_metadatas.append(metadatas[i])
                    filtered_embeddings.append(embeddings[i])
        else:
            # 空数据库直接保留所有文本
            filtered_texts = texts.copy()
            filtered_metadatas = metadatas.copy() if metadatas is not None else None
            filtered_embeddings = embeddings
        if not filtered_texts:
            return False  # 所有文本都被过滤

        # 添加到索引
        filtered_embeddings = np.array(filtered_embeddings).astype('float32')
        if self.index is None:
            self.index = faiss.IndexFlatL2(filtered_embeddings.shape[1])
        self.index.add(filtered_embeddings)

        # 处理元数据（避免修改原始输入）
        if len(filtered_metadatas) == 0:
            filtered_metadatas = [{"text": text} for text in filtered_texts]
        else:
            # 创建元数据副本并添加text字段
            filtered_metadatas = [
                {"text": text, **meta} 
                for text, meta in zip(filtered_texts, filtered_metadatas)
            ]
        self.metadata.extend(filtered_metadatas)
        print("-"*30)
        print(filtered_texts)

        # 保存数据库
        try:
            self._save_vector_db()
            return True
        except Exception as e:
            print(f"存储向量数据库失败: {e}")
            return False

    def retrieve(self, query:str, top_k:int=3, threshold:float=0.9) -> list[dict]:
        """
        从向量数据库检索相关文本
        
        参数:
            query: 查询文本
            top_k: 返回的最相关文本数量
        
        返回:
            包含元数据和相似度分数的字典列表
        """
        if self.index is None or self.index.ntotal == 0:
            return []

        with self.encode_lock:  # 扩大锁范围
            # 生成查询向量
            query_embedding = self.embedding_model.encode([query])
            query_embedding = np.array(query_embedding).astype('float32')

            # 搜索相似向量
            distances, indices = self.index.search(query_embedding, top_k*2)

        # 整理结果
        results = []
        for i in range(len(indices[0])):
            idx = indices[0][i]
            # 跳过无效索引
            if idx < 0 or idx >= len(self.metadata):
                # print("[retrieve] 无效索引: ", idx, len(self.metadata))
                continue
            
            # 计算相似度并过滤
            similarity = 1 / (1 + distances[0][i])  # 将L2距离转换为相似度分数
            print(f"sim:{similarity}, thrs:{threshold}")
            if similarity >= threshold:
                results.append({
                    "metadata": self.metadata[idx],
                    "similarity": similarity
                })
            
            # 提前终止：已收集足够数量的结果
            if len(results) >= top_k:
                break

        return results
    
    def retrieve_by_time(self, query: str, time_range: tuple[str, str], top_k: int = 3, threshold: float = 0.3, sort_by_time: bool=False) -> list[dict]:
        """
        按时间范围过滤后，仅在小范围数据中做相似度检索（仅重建筛选后向量，无全量重建开销）
        
        参数:
            query: 查询文本
            time_range: 时间范围元组 (start_timestamp, end_timestamp)
            top_k: 返回最相关的条目数
            threshold: 相似度阈值
        
        返回:
            与原retrieve格式一致的结果列表（含metadata和similarity）
        """
        # 边界条件：数据库为空
        if self.index is None or self.index.ntotal == 0 or len(self.metadata) == 0:
            return []
        
        # ===================== 第一步：O(n)过滤时间范围（无向量重建） =====================
        # 筛选出时间范围内的条目，记录idx和metadata（仅遍历metadata，无任何向量操作）
        filtered_indices = []  # 存储符合时间范围的向量索引idx
        filtered_metadata = [] # 存储对应的元数据
        start_ts, end_ts = time_range
        for idx, meta in enumerate(self.metadata):
            # 时间范围判断（包含边界，time=0表示未指定时间则跳过）
            if meta.get("time", "") >= start_ts and meta.get("time", "") <= end_ts:
                filtered_indices.append(idx)
                filtered_metadata.append(meta)
        
        # 无符合时间范围的数据
        if len(filtered_indices) == 0:
            # print("rag: 无符合时间范围的数据")
            return []
        
        # ===================== 第二步：仅重建筛选后的数据向量（O(k)） =====================
        # 批量重建筛选出的向量（比逐个reconstruct更高效）
        # 注意：reconstruct_n只能按连续索引重建，非连续则逐个重建（仍为O(k)）
        filtered_embeddings = []
        for idx in filtered_indices:
            # 仅重建筛选后的向量（k远小于n，开销极小）
            vec = self.index.reconstruct(idx).astype('float32')
            filtered_embeddings.append(vec)
        filtered_embeddings = np.array(filtered_embeddings)
        
        # ===================== 第三步：在小范围向量中做相似度检索 =====================
        # 生成查询向量
        with self.encode_lock:
            query_embedding = self.embedding_model.encode([query])
            query_embedding = np.array(query_embedding).astype('float32')
        
        # 构建临时FAISS索引（仅包含筛选后的向量），做相似度检索
        temp_index = faiss.IndexFlatL2(filtered_embeddings.shape[1])
        temp_index.add(filtered_embeddings)
        
        # 在临时索引中搜索（仅对小范围数据计算相似度）
        distances, temp_indices = temp_index.search(query_embedding, min(top_k, len(filtered_indices)))
        
        # 整理结果（映射回原metadata，过滤相似度阈值）
        results = []
        for i in range(len(temp_indices[0])):
            temp_idx = temp_indices[0][i]
            if temp_idx < 0 or temp_idx >= len(filtered_metadata):
                continue
            
            # 计算相似度（与原retrieve逻辑一致）
            similarity = 1 / (1 + distances[0][i])
            if similarity >= threshold:
                results.append({
                    "metadata": filtered_metadata[temp_idx],
                    "similarity": similarity
                })
        
        if sort_by_time:
            # 按时间索引排序
            results = sorted(results, key=lambda x: x["metadata"].get("time", ""), reverse=True)[:top_k]
        else:
            # 按相似度降序排序，取top_k
            results = sorted(results, key=lambda x: x["similarity"], reverse=True)[:top_k]
        
        return results

    def delete_by_text(self, target_text: str) -> bool:
        """
        按文本内容精准删除指定条目
        :param target_text: 要删除的文本内容
        :return: 是否删除成功
        """
        if self.index is None or self.index.ntotal == 0 or len(self.metadata) == 0:
            return False

        # 1. 找到目标文本对应的索引
        delete_indices = []
        new_metadata = []
        for idx, meta in enumerate(self.metadata):
            if meta.get("text") == target_text:
                delete_indices.append(idx)
            else:
                new_metadata.append(meta)

        if not delete_indices:
            print("未找到匹配的文本条目")
            return False

        # 2. 重建FAISS索引（FAISS不支持直接删除，需过滤后重建）
        # 提取所有保留的向量（排除要删除的索引）
        keep_vectors = []
        for idx in range(self.index.ntotal):
            if idx not in delete_indices:
                vec = self.index.reconstruct(idx).astype('float32')
                keep_vectors.append(vec)
        
        # 重新初始化索引并添加保留的向量
        if keep_vectors:
            self.index = faiss.IndexFlatL2(keep_vectors[0].shape[0])
            self.index.add(np.array(keep_vectors).astype('float32'))
        else:
            # 所有条目都被删除，初始化空索引
            self.index = faiss.IndexFlatL2(384)  # 384是模型输出维度
        
        # 3. 更新元数据并保存
        self.metadata = new_metadata
        self._save_vector_db()
        print(f"成功删除 {len(delete_indices)} 个匹配条目")
        return True

    def rebuild_database(self, similarity_threshold=0.95):
        """
        重建数据库，过滤语义相似度过高（超过阈值）的条目
        
        参数:
            similarity_threshold: 相似度阈值，超过此值的条目将被过滤
        """
        if self.index is None or self.index.ntotal == 0:
            return False  # 空数据库无需处理
        
        # 获取所有向量
        all_vectors = self.index.reconstruct_n(0, self.index.ntotal).astype('float32')
        n = len(all_vectors)
        if n <= 1:
            return True  # 单个条目无需处理
        
        # 标记需要保留的条目（初始全部保留）
        keep = [True] * n
        
        # O(n²) 对比所有条目对，标记相似度过高的条目
        for i in range(n):
            if not keep[i]:
                continue  # 已标记为删除的条目无需再对比
            
            # 从i+1开始对比后续条目
            for j in range(i + 1, n):
                if not keep[j]:
                    continue  # 已标记为删除的条目无需再对比
                
                # 计算余弦相似度（L2归一化后点积等价于余弦相似度）
                vec_i = all_vectors[i]
                vec_j = all_vectors[j]
                norm_i = np.linalg.norm(vec_i)
                norm_j = np.linalg.norm(vec_j)
                if norm_i == 0 or norm_j == 0:
                    similarity = 0.0
                else:
                    similarity = np.dot(vec_i / norm_i, vec_j / norm_j)
                
                # 相似度过高则标记为删除
                if similarity > similarity_threshold:
                    keep[j] = False
        
        # 收集需要保留的向量和元数据
        kept_vectors = []
        kept_metadata = []
        for i in range(n):
            if keep[i]:
                kept_vectors.append(all_vectors[i])
                kept_metadata.append(self.metadata[i])
        
        # 重建索引
        if kept_vectors:
            self.index = faiss.IndexFlatL2(all_vectors.shape[1])
            self.index.add(np.array(kept_vectors).astype('float32'))
            self.metadata = kept_metadata
        else:
            # 全部被过滤时初始化空索引
            self.index = faiss.IndexFlatL2(all_vectors.shape[1])
            self.metadata = []
        
        # 保存清洗后的数据库
        self._save_vector_db()
        return True

    def batch_rebuild_time(self) -> tuple[int, int]:
        """
        批量重构metadata：
        1. 从text首部提取[YYYY-MM-DD, HH:MM]时间，移除该部分内容；
        2. 将提取的时间转换为时间戳，存入time键；
        3. 未匹配到时间的条目，time设为0.0；
        返回：(成功重构的条目数, 总条目数)
        """
        if len(self.metadata) == 0:
            print("无元数据可重构")
            return (0, 0)
        
        total = len(self.metadata)
        success_count = 0
        updated_metadata = []
        last_time_str = ""

        for meta in self.metadata:
            # 深拷贝原metadata，避免修改原数据
            new_meta = meta.copy()
            text = new_meta.get("text", "")
            if not text:
                updated_metadata.append(new_meta)
                continue
            if "time" in meta:
                updated_metadata.append(new_meta)
                continue

            # 第一步：匹配text首部的时间字符串
            match = re.search(TIME_PATTERN, text)
            if match:
                # 提取时间字符串（如"2026-03-08, 12:18"）
                time_str = f"{match.group('date')}, {match.group('time')}"
                last_time_str = time_str
                # 更新metadata
                new_meta["time"] = time_str
                success_count += 1
            else:
                # 未匹配到时间，time设为上一条time_str的值
                new_meta["time"] = last_time_str
            
            updated_metadata.append(new_meta)

        # 替换原metadata并保存到磁盘
        self.metadata = updated_metadata
        self._save_vector_db()

        print(f"批量重构完成：总条目数={total}，成功提取时间条目数={success_count}")
        return (success_count, total)

if __name__ == "__main__":
    rag = RAGService(_vdb_path=global_config.VDB_DIARY_DIR)
    flag = rag.delete_by_text("day day day day day day day day day day day day day day day day day day day day ")
