# frozen_string_literal: true

# 허브 페이지 생성기 — 분야 7 · 대상 8 · 지역 18 · 전체/마감임박/신규 3
#
# 이 33개를 stub 파일로 두면 분류를 하나 고칠 때마다 파일을 손대야 한다.
# `_data/taxonomy.json`(scripts/taxonomy.py 가 내보냄) 하나만 진실로 두고
# 페이지는 빌드 시점에 만든다.
#
# 커스텀 플러그인을 쓸 수 있는 이유: 배포가 GitHub Pages 기본 빌더가 아니라
# 워크플로우 안의 `bundle exec jekyll build` + peaceiris/actions-gh-pages 이기 때문이다.
# (REDESIGN.md §5.2)
module Walapp
  class HubPage < Jekyll::PageWithoutAFile
    def initialize(site, url, attrs)
      super(site, site.source, "", "index.html")
      self.data = attrs.merge("layout" => "hub", "permalink" => url)
      self.content = ""
    end
  end

  class HubGenerator < Jekyll::Generator
    safe true
    priority :normal

    def generate(site)
      taxonomy = site.data["taxonomy"]
      unless taxonomy
        Jekyll.logger.warn "HubGenerator:",
                           "_data/taxonomy.json 이 없습니다. `python3 scripts/run_all.py` 를 먼저 실행하세요."
        return
      end

      add_fixed_hubs(site)
      add_category_hubs(site, taxonomy)
      add_audience_hubs(site, taxonomy)
      add_region_hubs(site, taxonomy)

      Jekyll.logger.info "HubGenerator:", "허브 페이지 #{@count} 개 생성"
    end

    private

    def push(site, url, attrs)
      @count = (@count || 0) + 1
      site.pages << HubPage.new(site, url, attrs)
    end

    def add_fixed_hubs(site)
      push(site, "/support/",
           "title"     => "전체 지원 제도",
           "heading"   => "전체 지원 제도",
           "eyebrow"   => "지원 제도",
           "blurb"     => "정부와 지방자치단체가 운영하는 지원 제도를 분야별로 모았습니다. 받을 수 있는 조건과 신청 방법을 하나씩 정리합니다.",
           "hub_axis"  => "all",
           "footnote"  => "금액과 자격 요건은 지침 개정으로 수시로 바뀝니다. 신청 전 각 제도의 공식 창구에서 최신 내용을 확인해 주세요.")

      push(site, "/deadline/",
           "title"     => "마감 임박 지원금",
           "heading"   => "마감이 다가오는 제도",
           "eyebrow"   => "마감 임박",
           "blurb"     => "신청 기한이 정해진 제도를 마감일이 가까운 순으로 정렬했습니다. 상시 접수 제도는 제외했습니다.",
           "hub_axis"  => "deadline",
           "footnote"  => "예산이 일찍 소진되면 표시된 마감일보다 먼저 접수가 끝날 수 있습니다.")

      push(site, "/new/",
           "title"     => "새로 추가된 제도",
           "heading"   => "새로 추가된 제도",
           "eyebrow"   => "신규",
           "blurb"     => "최근에 정리해 올린 제도입니다.",
           "hub_axis"  => "new")
    end

    def add_category_hubs(site, taxonomy)
      (taxonomy["category_order"] || []).each do |key|
        meta = taxonomy.dig("categories", key) || {}
        label = meta["label"] || key
        push(site, "/support/#{key}/",
             "title"    => "#{label} 지원 제도",
             "heading"  => "#{meta['emoji']} #{label}",
             "eyebrow"  => "분야별",
             "blurb"    => meta["desc"],
             "hub_axis" => "category",
             "hub_key"  => key)
      end
    end

    def add_audience_hubs(site, taxonomy)
      (taxonomy["audience_order"] || []).each do |key|
        meta = taxonomy.dig("audiences", key) || {}
        label = meta["label"] || key
        push(site, "/who/#{key}/",
             "title"    => "#{label} 지원금 총정리",
             "heading"  => "#{meta['emoji']} #{label}을(를) 위한 제도",
             "eyebrow"  => "대상별",
             "blurb"    => meta["desc"],
             "hub_axis" => "audience",
             "hub_key"  => key)
      end
    end

    def add_region_hubs(site, taxonomy)
      push(site, "/region/national/",
           "title"    => "전국 지원 제도",
           "heading"  => "전국 어디서나 신청 가능한 제도",
           "eyebrow"  => "지역별",
           "blurb"    => "거주 지역과 상관없이 신청할 수 있는 중앙부처 제도입니다.",
           "hub_axis" => "region",
           "hub_key"  => "national")

      # 중앙부처 우선 단계에서는 지자체 제도가 아직 없다. 빈 시도 허브를 17개
      # 만들면 내용 없는 페이지만 늘어 색인에 해롭다. 제도가 실제로 있는 시도만 만든다.
      # 지자체까지 범위를 넓히면 그날부터 자동으로 생긴다.
      programs = site.collections["programs"]&.docs || []
      populated = programs.map { |d| d.data["region_sido"] }.compact.uniq
      skipped = (taxonomy["sido_order"] || []).size - populated.size

      (taxonomy["sido_order"] || []).each do |key|
        next unless populated.include?(key)

        name = taxonomy.dig("sido", key) || key
        push(site, "/region/#{key}/",
             "title"    => "#{name} 지원금 총정리",
             "heading"  => "#{name} 지원 제도",
             "eyebrow"  => "지역별",
             "blurb"    => "#{name}에 거주하면 신청할 수 있는 제도를 모았습니다. 전국 단위 제도와 중복해서 받을 수 있는 경우도 있습니다.",
             "hub_axis" => "region",
             "hub_key"  => key)
      end

      return if skipped.zero?

      Jekyll.logger.info "HubGenerator:", "제도가 없는 시도 허브 #{skipped}개는 건너뜀"
    end
  end
end
