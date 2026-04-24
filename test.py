from neo4j import GraphDatabase, exceptions

# ===================== 【本地 Neo4j 配置】你自己的信息 =====================
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "12345678"
# =========================================================================

class KnowledgeGraphCRUD:
    """知识图谱增删改查接口实现"""
    def __init__(self, uri, user, password):
        """
        【全局只执行一次】
        程序启动时建立连接，之后永远复用
        """
        self.driver = GraphDatabase.driver(
            uri, 
            auth=(user, password),
            max_connection_pool_size=30,  # 连接池优化
            connection_timeout=10         # 超时控制
        )
        # 【关键】创建一个全局 session，全程复用
        self.session = self.driver.session()

    def close(self):
        """程序结束时才关闭"""
        if self.session:
            self.session.close()
        if self.driver:
            self.driver.close()

    # -------------------------- 节点操作：复用连接 --------------------------
    def create_node(self, label, properties):
        try:
            # 不再新建 session！直接用全局的
            query = f"CREATE (n:{label} $props) RETURN n"
            result = self.session.run(query, props=properties)
            node = result.single()["n"]
            return {
                "element_id": node.element_id,
                "label": list(node.labels)[0],
                "properties": dict(node.items())
            }
        except exceptions.Neo4jError as e:
            print(f"创建节点失败: {e}")
            return None

    def get_node(self, label, properties=None):
        try:
            if properties:
                filter_str = " AND ".join([f"n.{k} = ${k}" for k in properties.keys()])
                query = f"MATCH (n:{label}) WHERE {filter_str} RETURN n"
                result = self.session.run(query,** properties)
            else:
                query = f"MATCH (n:{label}) RETURN n"
                result = self.session.run(query)

            nodes = []
            for record in result:
                node = record["n"]
                nodes.append({
                    "element_id": node.element_id,
                    "label": list(node.labels)[0],
                    "properties": dict(node.items())
                })
            return nodes
        except:
            return []
    
    def update_node(self, label, match_properties, update_properties):
        try:
            match_str = " AND ".join([f"n.{k}=${k}" for k in match_properties.keys()])
            update_str = ", ".join([f"n.{k}=${k}_up" for k in update_properties.keys()])
            
            params = match_properties.copy()
            for k, v in update_properties.items():
                params[f"{k}_up"] = v

            query = f"MATCH (n:{label}) WHERE {match_str} SET {update_str} RETURN count(n)"
            result = self.session.run(query,** params)
            return result.single()[0]
        except:
            return 0

    def delete_node(self, label, properties):
        try:
            filter_str = " AND ".join([f"n.{k}=${k}" for k in properties.keys()])
            query = f"MATCH (n:{label}) WHERE {filter_str} DETACH DELETE n RETURN count(n)"
            result = self.session.run(query, **properties)
            return result.single()[0]
        except:
            return 0

    # -------------------------- 关系操作：复用连接 --------------------------
    def create_relationship(self, start_label, start_props, end_label, end_props, rel_type, rel_props=None):
        try:
            start_filter = " AND ".join([f"s.{k}=${k}_s" for k in start_props.keys()])
            end_filter = " AND ".join([f"e.{k}=${k}_e" for k in end_props.keys()])
            
            params = {}
            for k, v in start_props.items(): params[f"{k}_s"] = v
            for k, v in end_props.items(): params[f"{k}_e"] = v

            rel_prop_str = "SET r = $rel_props" if rel_props else ""
            
            query = f"""
            MATCH (s:{start_label}) WHERE {start_filter}
            MATCH (e:{end_label}) WHERE {end_filter}
            CREATE (s)-[r:{rel_type}]->(e) {rel_prop_str}
            RETURN r
            """
            result = self.session.run(query,** params, rel_props=rel_props or {})
            return result.single()["r"]
        except:
            return None
    
    def get_relationship(self, start_label=None, end_label=None, rel_type=None):
        """
        查询关系（支持按起始节点标签、结束节点标签、关系类型过滤）
        :param start_label: 起始节点标签（可选）
        :param end_label: 结束节点标签（可选）
        :param rel_type: 关系类型（可选）
        :return: 关系列表（list[dict]）
        """
        try:
            # 统一使用全局session
            match_parts = ["(s)", "-[r]", "->(e)"]
            if start_label:
                match_parts[0] = f"(s:{start_label})"
            if end_label:
                match_parts[2] = f"->(e:{end_label})"
            if rel_type:
                match_parts[1] = f"-[r:{rel_type}]"
            
            query = f"MATCH {''.join(match_parts)} RETURN r, s, e"
            result = self.session.run(query)
            
            rels = []
            for record in result:
                rel = record["r"]
                rels.append({
                    "element_id": rel.element_id,
                    "type": rel.type,
                    "properties": dict(rel.items()),
                    "start_node": {
                        "element_id": record["s"].element_id,
                        "label": list(record["s"].labels)[0] if record["s"].labels else None,
                        "properties": dict(record["s"].items())
                    },
                    "end_node": {
                        "element_id": record["e"].element_id,
                        "label": list(record["e"].labels)[0] if record["e"].labels else None,
                        "properties": dict(record["e"].items())
                    }
                })
            return rels
        except exceptions.Neo4jError as e:
            print(f"查询关系失败: {e}")
            return []
    
    def update_relationship(self, start_label, start_props, end_label, end_props, rel_type, update_props):
        """
        修改关系属性
        :param start_label: 起始节点标签
        :param start_props: 起始节点匹配属性
        :param end_label: 结束节点标签
        :param end_props: 结束节点匹配属性
        :param rel_type: 关系类型
        :param update_props: 要更新的关系属性字典
        :return: 更新的关系数量（int）
        """
        try:
            # 构建节点过滤条件
            start_filter = " AND ".join([f"s.{k}=${k}_s" for k in start_props.keys()])
            end_filter = " AND ".join([f"e.{k}=${k}_e" for k in end_props.keys()])
            # 构建属性更新语句
            update_str = ", ".join([f"r.{k}=${k}_up" for k in update_props.keys()])
            
            # 组装参数
            params = {}
            for k, v in start_props.items(): params[f"{k}_s"] = v
            for k, v in end_props.items(): params[f"{k}_e"] = v
            for k, v in update_props.items(): params[f"{k}_up"] = v

            query = f"""
            MATCH (s:{start_label}) WHERE {start_filter}
            MATCH (e:{end_label}) WHERE {end_filter}
            MATCH (s)-[r:{rel_type}]->(e)
            SET {update_str}
            RETURN count(r)
            """
            result = self.session.run(query, **params)
            return result.single()[0]
        except exceptions.Neo4jError as e:
            print(f"修改关系失败: {e}")
            return 0
    
    def delete_relationship(self, rel_type, start_props, end_props):
        """
        删除关系
        :param rel_type: 关系类型
        :param start_props: 起始节点匹配属性
        :param end_props: 结束节点匹配属性
        :return: 删除的关系数量（int）
        """
        try:
            start_filter = " AND ".join([f"s.{k} = ${k}_start" for k in start_props.keys()])
            end_filter = " AND ".join([f"e.{k} = ${k}_end" for k in end_props.keys()])
            
            params = {}
            for k, v in start_props.items():
                params[f"{k}_start"] = v
            for k, v in end_props.items():
                params[f"{k}_end"] = v
            
            query = f"""
            MATCH (s)-[r:{rel_type}]->(e)
            WHERE {start_filter} AND {end_filter}
            DELETE r
            RETURN count(r) as count
            """
            result = self.session.run(query,** params)
            return result.single()["count"]
        except exceptions.Neo4jError as e:
            print(f"删除关系失败: {e}")
            return 0

# 调用大模型自动从文本中提取关系
def KG_extract(text:str, KG_service:KnowledgeGraphCRUD) -> bool:
    if not text.strip() or not KG_service:
        print("输入文本或KG服务实例为空")
        return False
    pass
    return True




















# -------------------------- 测试示例 --------------------------
def main():
    # 初始化知识图谱CRUD实例
    kg = KnowledgeGraphCRUD(NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)
    
    print("===== 知识图谱交互式增删改查工具 =====")
    print("支持操作：1-创建节点 2-查询节点 3-更新节点 4-删除节点")
    print("          5-创建关系 6-查询关系 7-修改关系 8-删除关系 0-退出")
    print("=====================================\n")
    
    while True:
        try:
            choice = input("请输入操作编号(0-8)：").strip()
            if choice == "0":
                print("退出程序...")
                break
            
            # 1. 创建节点
            elif choice == "1":
                label = input("请输入节点标签：").strip()
                props = {}
                print("请输入节点属性（格式：键=值，输入空行结束）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    props[k.strip()] = v.strip()
                result = kg.create_node(label, props)
                if result:
                    print(f"✅ 创建节点成功：{result}")
                else:
                    print("❌ 创建节点失败")
            
            # 2. 查询节点
            elif choice == "2":
                label = input("请输入节点标签：").strip()
                props = {}
                print("请输入查询属性（格式：键=值，输入空行结束，留空查询所有该标签节点）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    props[k.strip()] = v.strip()
                result = kg.get_node(label, props if props else None)
                print(f"🔍 查询结果（共{len(result)}个节点）：")
                for node in result:
                    print(f"   {node}")
            
            # 3. 更新节点
            elif choice == "3":
                label = input("请输入节点标签：").strip()
                match_props = {}
                print("请输入匹配属性（格式：键=值，输入空行结束）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    match_props[k.strip()] = v.strip()
                
                update_props = {}
                print("请输入更新属性（格式：键=值，输入空行结束）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    update_props[k.strip()] = v.strip()
                
                count = kg.update_node(label, match_props, update_props)
                print(f"📝 更新完成，共更新 {count} 个节点")
            
            # 4. 删除节点
            elif choice == "4":
                label = input("请输入节点标签：").strip()
                props = {}
                print("请输入删除匹配属性（格式：键=值，输入空行结束）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    props[k.strip()] = v.strip()
                count = kg.delete_node(label, props)
                print(f"🗑️ 删除完成，共删除 {count} 个节点")
            
            # 5. 创建关系
            elif choice == "5":
                start_label = input("请输入起始节点标签：").strip()
                start_props = {}
                print("请输入起始节点匹配属性（格式：键=值，输入空行结束）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    start_props[k.strip()] = v.strip()
                
                end_label = input("请输入结束节点标签：").strip()
                end_props = {}
                print("请输入结束节点匹配属性（格式：键=值，输入空行结束）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    end_props[k.strip()] = v.strip()
                
                rel_type = input("请输入关系类型：").strip()
                rel_props = {}
                print("请输入关系属性（格式：键=值，输入空行结束，无属性直接回车）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    rel_props[k.strip()] = v.strip()
                
                result = kg.create_relationship(start_label, start_props, end_label, end_props, rel_type, rel_props)
                if result:
                    print(f"✅ 创建关系成功：{result}")
                else:
                    print("❌ 创建关系失败")
            
            # 6. 查询关系
            elif choice == "6":
                start_label = input("请输入起始节点标签（可选，直接回车跳过）：").strip() or None
                end_label = input("请输入结束节点标签（可选，直接回车跳过）：").strip() or None
                rel_type = input("请输入关系类型（可选，直接回车跳过）：").strip() or None
                
                result = kg.get_relationship(start_label, end_label, rel_type)
                print(f"🔍 查询结果（共{len(result)}个关系）：")
                for rel in result:
                    print(f"   {rel}")
            
            # 7. 修改关系
            elif choice == "7":
                start_label = input("请输入起始节点标签：").strip()
                start_props = {}
                print("请输入起始节点匹配属性（格式：键=值，输入空行结束）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    start_props[k.strip()] = v.strip()
                
                end_label = input("请输入结束节点标签：").strip()
                end_props = {}
                print("请输入结束节点匹配属性（格式：键=值，输入空行结束）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    end_props[k.strip()] = v.strip()
                
                rel_type = input("请输入关系类型：").strip()
                update_props = {}
                print("请输入要更新的关系属性（格式：键=值，输入空行结束）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    update_props[k.strip()] = v.strip()
                
                count = kg.update_relationship(start_label, start_props, end_label, end_props, rel_type, update_props)
                print(f"📝 修改完成，共更新 {count} 个关系")
            
            # 8. 删除关系
            elif choice == "8":
                rel_type = input("请输入关系类型：").strip()
                start_props = {}
                print("请输入起始节点匹配属性（格式：键=值，输入空行结束）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    start_props[k.strip()] = v.strip()
                
                end_props = {}
                print("请输入结束节点匹配属性（格式：键=值，输入空行结束）：")
                while True:
                    prop_input = input().strip()
                    if not prop_input:
                        break
                    k, v = prop_input.split("=", 1)
                    end_props[k.strip()] = v.strip()
                
                count = kg.delete_relationship(rel_type, start_props, end_props)
                print(f"🗑️ 删除完成，共删除 {count} 个关系")
            
            else:
                print("❌ 无效的操作编号，请输入0-8之间的数字")
            
            print("-" * 50 + "\n")  # 分隔线
            
        except Exception as e:
            print(f"❌ 操作出错：{str(e)}")
            print("-" * 50 + "\n")
    
    # 关闭连接
    kg.close()

if __name__ == "__main__":
    main()