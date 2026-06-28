from calibre.customize import InterfaceActionBase


class KindleCoverFixerBase(InterfaceActionBase):
    name                = 'Kindle Cover Fixer'
    description         = ('Automatically embed the cover (and a looked-up Amazon ASIN) into book '
                           'files when they are added/downloaded, so covers show on Kindle Colorsoft.')
    supported_platforms = ['windows', 'osx', 'linux']
    author              = 'Anonymous'
    version             = (0, 1, 13)
    minimum_calibre_version = (5, 0, 0)

    actual_plugin = 'calibre_plugins.kindle_cover_fixer.ui:KindleCoverFixer'

    def is_customizable(self):
        return True

    def config_widget(self):
        from calibre_plugins.kindle_cover_fixer.config import ConfigWidget
        return ConfigWidget()

    def save_settings(self, config_widget):
        config_widget.save_settings()
