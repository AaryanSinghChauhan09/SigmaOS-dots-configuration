#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DotfileMapping {
    pub source: String,
    pub target: String,
}

#[derive(Debug, Default)]
pub struct DotfilesManager {
    mappings: Vec<DotfileMapping>,
}

impl DotfilesManager {
    pub fn new() -> Self { Self { mappings: Vec::new() } }
    pub fn add_link(&mut self, src: &str, tgt: &str) {
        self.mappings.push(DotfileMapping { source: src.into(), target: tgt.into() });
    }
    pub fn count(&self) -> usize { self.mappings.len() }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_dotfiles_manager_aaa() {
        // Arrange
        let mut dm = DotfilesManager::new();
        // Act
        dm.add_link("configs/alacritty.toml", "~/.config/alacritty/alacritty.toml");
        // Assert
        assert_eq!(dm.count(), 1);
    }
}
