from django.core.paginator import InvalidPage, Page, Paginator

__all__ = ("DiggPaginator",)


class SoftPaginator(Paginator):
    def _ensure_int(self, num, e):
        try:
            return int(num)
        except (TypeError, ValueError):
            raise e from None

    def page(self, number, softlimit=False):
        try:
            return super().page(number)
        except InvalidPage as e:
            number = self._ensure_int(number, e)
            if number > self.num_pages and softlimit:
                return self.page(self.num_pages, softlimit=False)
            else:
                raise e from None


class DiggPaginator(SoftPaginator):
    def page(self, number, *args, **kwargs):
        kwargs.update({"softlimit": True})
        page = super().page(number, *args, **kwargs)
        page.__class__ = DiggPage
        return page


class DiggPage(Page):
    def elided_page_range(self):
        return self.paginator.get_elided_page_range(self.number)
