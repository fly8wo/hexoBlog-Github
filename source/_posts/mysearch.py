import re

from django.shortcuts import render
import json
from django.views.generic.base import View
from search.models import ArticleType, ZhiHuQuestionType, LagouType
from django.http import HttpResponse
from datetime import datetime
from mtianyanSearch.utils.common import OrderedSet
import redis

# 为搜索界面进行准备
from elasticsearch import Elasticsearch
client = Elasticsearch(hosts=["127.0.0.1"])
# 使用redis实现top n排行榜
redis_cli = redis.StrictRedis()

# Create your views here.


class IndexView(View):
    # 首页
    def get(self, request):
        topn_search_clean = []
        topn_search = redis_cli.zrevrangebyscore(
            "search_keywords_set", "+inf", "-inf", start=0, num=5)
        for topn_key in topn_search:
            topn_key = str(topn_key, encoding="utf-8")
            topn_search_clean.append(topn_key)
        topn_search = topn_search_clean
        return render(request, "index.html", {"topn_search": topn_search})


class SearchSuggest(View):
    def get(self, request):
        key_words = request.GET.get('s', '')
        current_page = request.GET.get('s_type', '')
        if current_page == "article":
            re_datas = []
            if key_words:
                s = ArticleType.search()
                # fuzzy模糊搜索。fuzziness 编辑距离 prefix_length前面不变化的前缀长度
                s = s.suggest('my_suggest', key_words, completion={
                    "field": "suggest", "fuzzy": {
                        "fuzziness": 2
                    },
                    "size": 10
                })
                suggestions = s.execute_suggest()
                for match in suggestions.my_suggest[0].options[:10]:
                    source = match._source
                    re_datas.append(source["title"])
                    # re_datas.append(source["content"])
            return HttpResponse(
                json.dumps(re_datas),
                content_type="application/json")
        elif current_page == "job":
            re_datas = []
            if key_words:
                s = LagouType.search()
                # fuzzy模糊搜索。fuzziness 编辑距离 prefix_length前面不变化的前缀长度
                s = s.suggest('my_suggest', key_words, completion={
                    "field": "suggest", "fuzzy": {
                        "fuzziness": 2
                    },
                    "size": 10
                })
                suggestions = s.execute_suggest()
                name_set = OrderedSet()
                for match in suggestions.my_suggest[0].options[:10]:
                    source = match._source
                    name_set.add(source["title"])
                for name in name_set:
                    re_datas.append(name)
                    # re_datas.append(source["content"])
            return HttpResponse(
                json.dumps(re_datas),
                content_type="application/json")
        elif current_page == "question":
            re_datas = []
            if key_words:
                s = ZhiHuQuestionType.search()
                # fuzzy模糊搜索。fuzziness 编辑距离 prefix_length前面不变化的前缀长度
                s = s.suggest('my_suggest', key_words, completion={
                    "field": "suggest", "fuzzy": {
                        "fuzziness": 2
                    },
                    "size": 10
                })
                name_set = OrderedSet()
                suggestions = s.execute_suggest()
                if suggestions:
                    for match in suggestions.my_suggest[0].options[:10]:
                        if match._type == "question":
                            source = match._source
                            re_datas.append(source["title"])
                        elif match._type == "answer":
                            source = match._source
                            name_set.add(source["author_name"])
                for name in name_set:
                    re_datas.append(name)
            return HttpResponse(
                json.dumps(re_datas),
                content_type="application/json")


class SearchView(View):
    def get(self, request):
        key_words = request.GET.get("q", "")

        # 通用部分
        # 实现搜索关键词keyword加1操作
        redis_cli.zincrby("search_keywords_set", key_words)
        # 获取topn个搜索词
        topn_search_clean = []
        topn_search = redis_cli.zrevrangebyscore(
            "search_keywords_set", "+inf", "-inf", start=0, num=5)
        for topn_key in topn_search:
            topn_key = str(topn_key, encoding="utf-8")
            topn_search_clean.append(topn_key)
        topn_search = topn_search_clean
        # 获取伯乐在线的文章数量
        jobbole_count = redis_cli.get("jobbole_count")

        # 当前要获取第几页的数据
        page = request.GET.get("p", "1")
        try:
            page = int(page)
        except BaseException:
            page = 1
        response = []
        start_time = datetime.now()
        s_type = request.GET.get("s_type", "")
        if s_type == "article":
            response = client.search(
                index="jobbole",
                body={
                    "query": {
                        "multi_match": {
                            "query": key_words,
                            "fields": ["title", "tags", "content"]
                        }
                    },
                    "from": (page - 1) * 10,
                    "size": 10,
                    "highlight": {
                        "pre_tags": ['<span class="keyWord">'],
                        "post_tags": ['</span>'],
                        "fields": {
                            "title": {},
                            "content": {},
                        }
                    }
                }
            )
        elif s_type == "job":
            response = client.search(
                index="lagou",
                body={
                    "query": {
                        "multi_match": {
                            "query": key_words,
                            "fields": [
                                "tags",
                                "title",
                                "job_advantage",
                                "job_desc",
                                "company_name",
                                "job_addr",
                                "job_city",
                                "degree_need"]}},
                    "from": (
                        page - 1) * 10,
                    "size": 10,
                    "highlight": {
                        "pre_tags": ['<span class="keyWord">'],
                        "post_tags": ['</span>'],
                        "fields": {
                            "title": {},
                            "content": {},
                        }}})
        elif s_type == "question":
            response = client.search(
                index="zhihu",
                body={
                    "query": {
                        "multi_match": {
                            "query": key_words,
                            "fields": [
                                "topics",
                                "title",
                                "content",
                                "author_name"]}},
                    "from": (
                        page - 1) * 10,
                    "size": 10,
                    "highlight": {
                        "pre_tags": ['<span class="keyWord">'],
                        "post_tags": ['</span>'],
                        "fields": {
                            "title": {},
                            "content": {},
                        }}})

        end_time = datetime.now()
        last_seconds = (end_time - start_time).total_seconds()
        total_nums = response["hits"]["total"]

        # 计算出总页数
        if (page % 10) > 0:
            page_nums = int(total_nums / 10) + 1
        else:
            page_nums = int(total_nums / 10)

        # 伯乐在线具体的信息
        hit_list = []
        hit_dict = {}
        if s_type == "article":
            for hit in response["hits"]["hits"]:
                if hit["highlight"]:
                    if "title" in hit["highlight"]:
                        hit_dict["title"] = "".join(hit["highlight"]["title"])
                    else:
                        hit_dict["title"] = hit["_source"]["title"]
                    if "content" in hit["highlight"]:
                        hit_dict["content"] = "".join(
                            hit["highlight"]["content"])[:500]
                    else:
                        hit_dict["content"] = hit["_source"]["content"][:500]

                    hit_dict["create_date"] = hit["_source"]["create_date"]
                    hit_dict["url"] = hit["_source"]["url"]
                    hit_dict["score"] = hit["_score"]
                    hit_list.append(hit_dict)
        elif s_type == "job":
            for hit in response["hits"]["hits"]:
                try:
                    if hit["highlight"]:
                        if "title" in hit["highlight"]:
                            hit_dict["title"] = "".join(
                                hit["highlight"]["title"])
                        else:
                            hit_dict["title"] = hit["_source"]["title"]
                        if "job_desc" in hit["highlight"]:
                            hit_dict["content"] = "".join(
                                hit["highlight"]["job_desc"])
                        else:
                            hit_dict["content"] = hit["_source"]["job_desc"]

                        hit_dict["create_date"] = hit["_source"]["publish_time"]
                        hit_dict["url"] = hit["_source"]["url"]
                        hit_dict["score"] = hit["_score"]
                except BaseException:
                    hit_dict["title"] = hit["_source"]["title"]
                    hit_dict["content"] = hit["_source"]["job_desc"]
                    hit_dict["create_date"] = hit["_source"]["publish_time"]
                    hit_dict["url"] = hit["_source"]["url"]
                    hit_dict["score"] = hit["_score"]
            hit_list.append(hit_dict)
        elif s_type == "question":
            for hit in response["hits"]["hits"]:
                try:
                    if hit["highlight"]:
                        if "title" in hit["highlight"]:
                            hit_dict["title"] = "".join(
                                hit["highlight"]["title"])
                        else:
                            try:
                                hit_dict["title"] = hit["_source"]["title"]
                            except BaseException:
                                hit_dict["title"] = hit["_source"]["author_name"]
                        if "content" in hit["highlight"]:
                            hit_dict["content"] = "".join(
                                hit["highlight"]["content"])
                        else:
                            hit_dict["content"] = hit["_source"]["content"]
                        try:
                            hit_dict["create_date"] = hit["_source"]["update_time"]
                        except BaseException:
                            hit_dict["create_date"] = hit["_source"]["crawl_time"]
                        if hit["_type"] == "answer":
                            data_url = hit["_source"]["url"]
                            match_url = re.match(".*answers/(\d+)")
                            question_id = 266139470
                            answer_id = match_url.group(1)
                            hit_dict["url"] = "https://www.zhihu.com/question/{0}/answer/{1}".format(
                                question_id, answer_id)
                        hit_dict["score"] = hit["_score"]
                except BaseException:
                    hit_dict["title"] = hit["_source"]["title"]
                    hit_dict["content"] = hit["_source"]["job_desc"]
                    hit_dict["create_date"] = hit["_source"]["publish_time"]
                    hit_dict["url"] = hit["_source"]["url"]
                    hit_dict["score"] = hit["_score"]
            hit_list.append(hit_dict)
        return render(request, "result.html", {"page": page,
                                               "all_hits": hit_list,
                                               "key_words": key_words,
                                               "total_nums": total_nums,
                                               "page_nums": page_nums,
                                               "last_seconds": last_seconds,
                                               "topn_search": topn_search,
                                               "jobbole_count": jobbole_count,
                                               })

    #
