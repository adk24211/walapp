# 세 자리마다 쉼표. 소개 화면의 커버리지 숫자에서만 쓴다.
#
# 왜 필터가 필요했나: 사이트가 화면에 내는 수는 지금까지 전부 네 자리 미만이라
# ("총 405건", "89건") 그냥 찍어도 읽혔다. 커버리지는 원천 10,961건이 나오는데
# "10961건" 은 한 번에 안 읽힌다.
#
# Liquid 에는 자리 구분 필터가 없고, divided_by/modulo 로 흉내 내면 자릿수마다
# 분기가 생겨 템플릿이 읽기 어려워진다. 다섯 줄짜리 필터가 낫다.
#
# ⚠️ GitHub Pages 의 기본 빌드는 커스텀 플러그인을 무시하지만, 이 저장소는
#    워크플로에서 `bundle exec jekyll build` 를 직접 돌린 뒤 결과를 gh-pages 로
#    올린다(_plugins/hub_generator.rb 가 같은 이유로 동작한다).
module Jekyll
  module NumberFilters
    # 정수로 읽히지 않는 값은 건드리지 않고 그대로 돌려준다. 화면에 "0" 이나
    # 빈 칸이 튀어나오는 것보다 원래 값이 보이는 편이 고치기 쉽다.
    def comma(input)
      return input if input.nil?

      s = input.to_s.strip
      return input unless s.match?(/\A-?\d+\z/)

      sign = s.start_with?("-") ? "-" : ""
      digits = s.delete_prefix("-")
      sign + digits.reverse.scan(/\d{1,3}/).join(",").reverse
    end
  end
end

Liquid::Template.register_filter(Jekyll::NumberFilters)
