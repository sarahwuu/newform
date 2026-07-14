from . import github_lists, greenhouse, lever, ashby, linkedin

REGISTRY = {
    "github_lists": github_lists.fetch,
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "linkedin": linkedin.fetch,
}
